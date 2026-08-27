"""AnyVoice — drop a book, get a full-cast audiobook, start listening while it renders."""
from __future__ import annotations
import os, re, shutil, tempfile
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from anyvoice.pipeline import Library, NARRATOR
from anyvoice.tts import VOICES, AUDIO_DIR
from anyvoice.ambience import ensure_all, AMB_DIR, AMBIENCES
from anyvoice.export import Exporter

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="AnyVoice")
lib = Library()
AMB_FILES = ensure_all()
PREVIEW = "Hello there. I could be the voice of this character, reading every line they speak in the story."


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


def _lan_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return None


@app.get("/api/status")
def status():
    return {"llm": bool(lib.llm), "lan_ip": _lan_ip(), "llm_provider": getattr(lib.llm, "provider", None), "llm_model": getattr(lib.llm, "model", None),
            "llm_error": lib.llm_error, "books": len(lib.books)}


@app.get("/api/ambience")
def ambience():
    return {"loops": AMB_FILES, "names": AMBIENCES}


@app.get("/api/voices")
def voices():
    return VOICES


@app.get("/api/voices/{voice}/preview")
def voice_preview(voice: str):
    if voice not in VOICES:
        raise HTTPException(404)
    fname, _ = lib.tts.synth(PREVIEW, voice)
    return FileResponse(AUDIO_DIR / fname, media_type="audio/wav")


@app.get("/api/books")
def books():
    out = []
    for job in lib.books.values():
        s = job.summary()
        segs = sum(c["segments"] for c in s["chapters"]); ready = sum(c["ready"] for c in s["chapters"])
        out.append({k: s[k] for k in ("id", "title", "author", "attribution")} |
                   {"chapters": len(s["chapters"]), "attributed": sum(c["status"] == "ready" for c in s["chapters"]),
                    "segments": segs, "ready": ready, "created": job.state["created"]})
    return sorted(out, key=lambda b: -b["created"])


@app.post("/api/books")
async def upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "book.txt").suffix.lower() or ".txt"
    if suffix not in (".epub", ".pdf", ".txt", ".md"):
        raise HTTPException(400, "upload an .epub, .pdf or .txt")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp); path = Path(tmp.name)
    try:
        job = lib.add(path)
    except Exception as e:
        raise HTTPException(400, f"could not read book: {e}")
    finally:
        path.unlink(missing_ok=True)
    return {"id": job.bid, "title": job.state["title"], "chapters": len(job.state["chapters"])}


SAMPLE_URL = "https://www.gutenberg.org/cache/epub/1342/pg1342-images.epub"

@app.post("/api/books/sample")
def sample_book():
    import urllib.request
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as tmp:
        req = urllib.request.Request(SAMPLE_URL, headers={"User-Agent": "Mozilla/5.0 AnyVoice"})
        with urllib.request.urlopen(req, timeout=60) as r:
            shutil.copyfileobj(r, tmp)
        path = Path(tmp.name)
    try:
        job = lib.add(path)
    except Exception as e:
        raise HTTPException(400, f"could not read sample: {e}")
    finally:
        path.unlink(missing_ok=True)
    return {"id": job.bid, "title": job.state["title"]}


def _job(bid: str):
    job = lib.books.get(bid)
    if not job:
        raise HTTPException(404, "no such book")
    return job


@app.get("/api/books/{bid}")
def book(bid: str):
    return _job(bid).summary()


@app.delete("/api/books/{bid}")
def delete_book(bid: str):
    _job(bid); lib.delete(bid); return {"ok": True}


@app.get("/api/books/{bid}/chapters/{idx}")
def chapter(bid: str, idx: int):
    job = _job(bid)
    if not 0 <= idx < len(job.state["chapters"]):
        raise HTTPException(404)
    return job.chapter(idx)


class Cursor(BaseModel):
    chapter: int
    seg: int = 0

@app.post("/api/books/{bid}/cursor")
def cursor(bid: str, c: Cursor):
    _job(bid).set_cursor(c.chapter, c.seg); return {"ok": True}


class VoiceSwap(BaseModel):
    name: str
    voice: str

@app.post("/api/books/{bid}/voice")
def swap_voice(bid: str, v: VoiceSwap):
    job = _job(bid)
    if v.name != NARRATOR and v.name not in job.state["cast"]:
        raise HTTPException(404, "no such character")
    try:
        job.set_voice(v.name, v.voice)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


_exporters: dict[str, Exporter] = {}
def _exporter(bid: str) -> Exporter:
    job = _job(bid)
    if bid not in _exporters:
        _exporters[bid] = Exporter(job)
    return _exporters[bid]


class ExportReq(BaseModel):
    ambience: str = "off"     # off | low | mid

@app.post("/api/books/{bid}/export")
def export_start(bid: str, r: ExportReq):
    return _exporter(bid).start(r.ambience)

@app.get("/api/books/{bid}/export")
def export_status(bid: str):
    return _exporter(bid).state

@app.get("/api/books/{bid}/export/download")
def export_download(bid: str):
    ex = _exporter(bid)
    if ex.state["status"] != "done" or not ex.state["file"]:
        raise HTTPException(404, "no export yet")
    return FileResponse(ex.dir / ex.state["file"], media_type="audio/mp4", filename=ex.state["file"])

@app.get("/api/books/{bid}/chapters/{idx}/mp3")
def chapter_mp3(bid: str, idx: int, ambience: str = "off"):
    job = _job(bid)
    c = job.chapter(idx)
    if c["status"] != "ready" or not all(s["audio"] for s in c["segments"]):
        raise HTTPException(409, "chapter not fully rendered yet")
    p = _exporter(bid).chapter_mp3(idx, ambience)
    safe = re.sub(r"[^\w\s-]", "", c["title"]).strip() or f"chapter-{idx}"
    return FileResponse(p, media_type="audio/mpeg", filename=f"{safe}.mp3")


app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")
app.mount("/ambience", StaticFiles(directory=str(AMB_DIR)), name="ambience")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
