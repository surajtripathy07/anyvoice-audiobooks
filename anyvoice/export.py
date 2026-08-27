"""Export a rendered book as an .m4b audiobook (AAC, chapter markers) or a single chapter as .mp3.
Optionally mixes the scene ambience in at the same low level the player uses."""
from __future__ import annotations
import json, re, subprocess, threading, traceback
from pathlib import Path
import numpy as np
import soundfile as sf
from .tts import AUDIO_DIR
from .ambience import AMB_DIR, SR as AMB_SR

SR = 24000
AMB_GAIN = {"off": 0.0, "low": 0.12, "mid": 0.22}
XFADE = 3.0


def _load(fname: str) -> np.ndarray:
    x, sr = sf.read(str(AUDIO_DIR / fname), dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != SR:
        x = np.interp(np.linspace(0, len(x), int(len(x) * SR / sr), endpoint=False), np.arange(len(x)), x).astype(np.float32)
    return x


_amb_cache: dict[str, np.ndarray] = {}
def _amb(name: str) -> np.ndarray:
    if name not in _amb_cache:
        x, sr = sf.read(str(AMB_DIR / f"{name}.wav"), dtype="float32")
        if sr != SR:
            x = np.interp(np.linspace(0, len(x), int(len(x) * SR / sr), endpoint=False), np.arange(len(x)), x).astype(np.float32)
        _amb_cache[name] = x
    return _amb_cache[name]


def mix_chapter(segments: list[dict], amb_level: str = "off") -> np.ndarray:
    """Concatenate segment audio; overlay looping ambience per scene with crossfades."""
    parts, spans, t = [], [], 0
    for s in segments:
        if not s.get("audio") or s["audio"] == "skip":
            continue
        x = _load(s["audio"]); parts.append(x)
        spans.append((t, t + len(x), s.get("amb", "none"))); t += len(x)
    if not parts:
        return np.zeros(0, np.float32)
    voice = np.concatenate(parts)
    gain = AMB_GAIN.get(amb_level, 0.0)
    if gain <= 0:
        return voice
    # collapse spans into scenes
    scenes = []
    for a, b, name in spans:
        if scenes and scenes[-1][2] == name:
            scenes[-1] = (scenes[-1][0], b, name)
        else:
            scenes.append((a, b, name))
    bed = np.zeros_like(voice); xf = int(XFADE * SR)
    for a, b, name in scenes:
        if name == "none":
            continue
        loop = _amb(name); n = b - a
        tile = np.tile(loop, n // len(loop) + 1)[:n]
        env = np.ones(n, np.float32)
        k = min(xf, n // 2)
        env[:k] = np.linspace(0, 1, k); env[-k:] = np.linspace(1, 0, k)
        bed[a:b] += tile * env
    out = voice + bed * gain
    return np.clip(out, -1, 1).astype(np.float32)


class Exporter:
    def __init__(self, job):
        self.job = job
        self.dir = job.dir / "export"; self.dir.mkdir(exist_ok=True)
        self.state = {"status": "idle", "progress": 0, "total": 0, "file": None, "error": None, "chapters": 0}
        self.thread = None

    def start(self, amb_level: str = "off"):
        if self.state["status"] == "running":
            return self.state
        self.state.update(status="running", progress=0, file=None, error=None)
        self.thread = threading.Thread(target=self._run, args=(amb_level,), daemon=True); self.thread.start()
        return self.state

    def _run(self, amb_level: str):
        try:
            with self.job.lock:
                st = json.loads(json.dumps(self.job.state))
            ready = [c for c in st["chapters"] if c["status"] == "ready" and c["segments"] and all(s["audio"] for s in c["segments"])]
            self.state.update(total=len(ready), chapters=len(ready))
            title = re.sub(r"[^\w\s-]", "", st["title"]).strip() or "audiobook"
            parts, meta, t_ms = [], [";FFMETADATA1", f"title={st['title']}", f"artist={st['author']}", "album=AnyVoice"], 0
            for i, c in enumerate(ready):
                x = mix_chapter(c["segments"], amb_level)
                wav = self.dir / f"ch{c['idx']:03d}.wav"; m4a = self.dir / f"ch{c['idx']:03d}.m4a"
                sf.write(str(wav), x, SR, subtype="PCM_16")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "64k", "-ac", "1", str(m4a)], check=True)
                wav.unlink()
                dur_ms = int(len(x) / SR * 1000)
                meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={t_ms}", f"END={t_ms + dur_ms}", f"title={c['title']}"]
                t_ms += dur_ms; parts.append(m4a)
                self.state["progress"] = i + 1
            (self.dir / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts))
            (self.dir / "meta.txt").write_text("\n".join(meta) + "\n")
            out = self.dir / f"{title}.m4b"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(self.dir / "list.txt"),
                            "-i", str(self.dir / "meta.txt"), "-map_metadata", "1", "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
            for p in parts:
                p.unlink()
            self.state.update(status="done", file=out.name)
        except Exception as e:
            traceback.print_exc(); self.state.update(status="error", error=str(e)[:300])

    def chapter_mp3(self, idx: int, amb_level: str = "off") -> Path:
        with self.job.lock:
            c = json.loads(json.dumps(self.job.state["chapters"][idx]))
        out = self.dir / f"ch{idx:03d}-{amb_level}.mp3"
        if out.exists():
            return out
        x = mix_chapter(c["segments"], amb_level)
        wav = out.with_suffix(".wav"); sf.write(str(wav), x, SR, subtype="PCM_16")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "96k", str(out)], check=True)
        wav.unlink(); return out
