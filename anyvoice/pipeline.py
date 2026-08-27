"""Per-book processing: attribution (LLM or heuristic) one chapter ahead, TTS in listening order,
state persisted to data/books/<id>/book.json so the player can poll it."""
from __future__ import annotations
import json, os, threading, time, traceback, uuid
from pathlib import Path
from .ingest import load_book
from .segmenter import split_units, render_for_llm, chunk_for_tts
from .tts import TTS, VOICES, DEFAULT_NARRATOR, pick_voice
from . import heuristic

DATA = Path(__file__).resolve().parent.parent / "data"
BOOKS = DATA / "books"
NARRATOR = "Narrator"
LOOKAHEAD = 2   # chapters to attribute ahead of the listening cursor


class Library:
    def __init__(self):
        BOOKS.mkdir(parents=True, exist_ok=True)
        self.tts = TTS()
        self.llm = None
        self.llm_error = None
        try:
            from .llm import LLM
            self.llm = LLM()
        except Exception as e:                       # no key configured etc.
            self.llm_error = str(e)
        self.books: dict[str, "BookJob"] = {}
        for d in sorted(BOOKS.iterdir()):
            if (d / "book.json").exists():
                self.books[d.name] = BookJob(self, d.name)

    def add(self, upload_path: Path) -> "BookJob":
        bid = uuid.uuid4().hex[:10]
        bdir = BOOKS / bid; bdir.mkdir()
        book = load_book(upload_path)
        (bdir / "chapters.json").write_text(json.dumps([{"title": c.title, "text": c.text} for c in book.chapters]))
        state = {
            "id": bid, "title": book.title, "author": book.author, "created": time.time(),
            "narrator_voice": DEFAULT_NARRATOR, "cast": {}, "cursor": 0,
            "chapters": [{"idx": i, "title": c.title, "words": c.words, "status": "pending", "segments": []}
                         for i, c in enumerate(book.chapters)],
            "attribution": "llm" if self.llm else "heuristic", "usage": {"input": 0, "output": 0}, "errors": [],
        }
        (bdir / "book.json").write_text(json.dumps(state))
        job = BookJob(self, bid); self.books[bid] = job
        return job

    def delete(self, bid: str):
        job = self.books.pop(bid, None)
        if job:
            job.stop = True
            import shutil; shutil.rmtree(BOOKS / bid, ignore_errors=True)


class BookJob:
    def __init__(self, lib: Library, bid: str):
        self.lib, self.bid = lib, bid
        self.dir = BOOKS / bid
        self.lock = threading.RLock()
        self.state = json.loads((self.dir / "book.json").read_text())
        self.texts = json.loads((self.dir / "chapters.json").read_text())
        self.stop = False
        self.wake = threading.Event()
        threading.Thread(target=self._attrib_loop, daemon=True, name=f"attrib-{bid}").start()
        threading.Thread(target=self._synth_loop, daemon=True, name=f"synth-{bid}").start()

    # ------------------------------------------------------------ state
    def save(self):
        with self.lock:
            tmp = self.dir / "book.json.tmp"
            tmp.write_text(json.dumps(self.state)); tmp.replace(self.dir / "book.json")

    def summary(self) -> dict:
        with self.lock:
            s = self.state
            chs = [{k: c[k] for k in ("idx", "title", "words", "status")} |
                   {"segments": len(c["segments"]), "ready": sum(1 for x in c["segments"] if x["audio"]),
                    "duration": round(sum(x["dur"] for x in c["segments"]), 1)} for c in s["chapters"]]
            return {k: s[k] for k in ("id", "title", "author", "narrator_voice", "cast", "cursor", "attribution", "usage", "errors")} | {"chapters": chs}

    def chapter(self, idx: int) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.state["chapters"][idx]))

    def set_cursor(self, idx: int, seg: int = 0):
        with self.lock:
            self.state["cursor"] = max(0, min(idx, len(self.state["chapters"]) - 1))
            self.state["cursor_seg"] = max(0, seg)
        self.wake.set()

    def set_voice(self, name: str, voice: str):
        if voice not in VOICES:
            raise ValueError("unknown voice")
        with self.lock:
            if name == NARRATOR:
                self.state["narrator_voice"] = voice
            else:
                self.state["cast"].setdefault(name, {})["voice"] = voice
            for c in self.state["chapters"]:
                for seg in c["segments"]:
                    if seg["speaker"] == name:
                        seg["voice"] = voice; seg["audio"] = None; seg["dur"] = 0.0
        self.save(); self.wake.set()

    def voice_for(self, speaker: str) -> str:
        s = self.state
        return s["narrator_voice"] if speaker == NARRATOR else s["cast"].get(speaker, {}).get("voice", s["narrator_voice"])

    # ------------------------------------------------------------ attribution
    def _next_to_attribute(self):
        with self.lock:
            chs, cur = self.state["chapters"], self.state["cursor"]
            for c in chs[cur:cur + LOOKAHEAD + 1]:
                if c["status"] == "pending":
                    return c["idx"]
            for c in chs:                    # then everything else, in order
                if c["status"] == "pending":
                    return c["idx"]
        return None

    def _attrib_loop(self):
        while not self.stop:
            idx = self._next_to_attribute()
            if idx is None:
                self.wake.wait(5); self.wake.clear(); continue
            try:
                self._attribute(idx)
            except Exception as e:
                traceback.print_exc()
                with self.lock:
                    self.state["errors"].append(f"ch{idx}: {e}"[:300])
                    self.state["chapters"][idx]["status"] = "pending"
                self.save(); time.sleep(10)

    def _attribute(self, idx: int):
        with self.lock:
            self.state["chapters"][idx]["status"] = "attributing"
            roster = [{"name": n} | v for n, v in self.state["cast"].items()]
            title = self.state["title"]
        self.save()
        ch = self.texts[idx]
        units = split_units(ch["text"])
        if self.lib.llm and self.state["attribution"] == "llm":
            attr = self.lib.llm.attribute(title, ch["title"], render_for_llm(units), roster)
        else:
            attr = heuristic.attribute(units, roster)
        label = {l.id: l for l in attr.lines}
        with self.lock:
            s = self.state
            british = s["narrator_voice"].startswith("b")
            for c in attr.characters:                       # new / updated characters -> cast
                entry = s["cast"].setdefault(c.name, {})
                for k in ("gender", "age", "description", "aliases"):
                    v = getattr(c, k)
                    if v and v != "unknown":
                        entry[k] = v
                if "voice" not in entry:
                    taken = {v.get("voice") for v in s["cast"].values()}
                    entry["voice"] = pick_voice(entry, taken, s["narrator_voice"], british)
            for l in attr.lines:                              # speakers the model named without a character entry
                if l.speaker != NARRATOR and l.speaker not in s["cast"]:
                    taken = {v.get("voice") for v in s["cast"].values()}
                    s["cast"][l.speaker] = {"gender": "unknown", "age": "unknown", "description": "",
                                            "voice": pick_voice({}, taken, s["narrator_voice"], british)}
            segs, i = [], 0
            for u in units:
                speaker, emotion = NARRATOR, "neutral"
                if u.kind == "quote" and u.id in label:
                    speaker, emotion = label[u.id].speaker, label[u.id].emotion
                for piece in chunk_for_tts(u.text):
                    segs.append({"i": i, "speaker": speaker, "emotion": emotion, "text": piece,
                                 "voice": self.voice_for(speaker), "audio": None, "dur": 0.0}); i += 1
            s["chapters"][idx]["segments"] = segs
            s["chapters"][idx]["status"] = "ready"
            if self.lib.llm:
                s["usage"] = dict(self.lib.llm.usage)
        self.save(); self.wake.set()

    # ------------------------------------------------------------ synthesis
    def _next_to_synth(self):
        with self.lock:
            chs, cur, cseg = self.state["chapters"], self.state["cursor"], self.state.get("cursor_seg", 0)
            order = chs[cur:] + chs[:cur]
            for n, c in enumerate(order):
                if c["status"] != "ready":
                    if c["idx"] >= cur:    # don't skip ahead past an unattributed chapter in listening order
                        return None
                    continue
                segs = c["segments"]
                if n == 0:                 # current chapter: from the listening position, then the part already passed
                    segs = segs[cseg:] + segs[:cseg]
                for seg in segs:
                    if not seg["audio"]:
                        return c["idx"], seg["i"], seg["text"], seg["voice"], seg["emotion"], seg["speaker"]
        return None

    def _synth_loop(self):
        while not self.stop:
            job = self._next_to_synth()
            if job is None:
                self.wake.wait(2); self.wake.clear(); continue
            cidx, sidx, text, voice, emotion, speaker = job
            try:
                fname, dur = self.lib.tts.synth(text, voice, emotion, dialogue=(speaker != NARRATOR))
            except Exception as e:
                traceback.print_exc()
                fname, dur = "", 0.0
                with self.lock:
                    self.state["errors"].append(f"tts ch{cidx} seg{sidx}: {e}"[:300])
            with self.lock:
                seg = self.state["chapters"][cidx]["segments"][sidx]
                if seg["voice"] == voice:               # voice may have been swapped meanwhile
                    seg["audio"], seg["dur"] = (fname or "skip"), dur
            if sidx % 10 == 0:
                self.save()
        self.save()
