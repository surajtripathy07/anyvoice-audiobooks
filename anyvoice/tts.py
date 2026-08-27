"""Kokoro TTS wrapper + voice bank + rule-based casting. Audio cached by content hash."""
from __future__ import annotations
import hashlib, io, json, os, re, threading, urllib.request
from pathlib import Path
import numpy as np
import soundfile as sf

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
AUDIO_DIR = Path(__file__).resolve().parent.parent / "data" / "audio"
PROMPT_DIR = Path(__file__).resolve().parent.parent / "data" / "prompts"
CHATTERBOX_URL = os.environ.get("CHATTERBOX_URL", "http://127.0.0.1:8091")
PROMPT_TEXT = ("Well, I suppose that settles it, then. We shall leave at first light, and I would rather you did not "
               "argue the point any further tonight.")
# emotion -> (exaggeration, cfg_weight) for Chatterbox; lower cfg = freer, more expressive delivery
EXPRESS = {"neutral": (0.45, 0.5), "happy": (0.6, 0.4), "sad": (0.4, 0.45), "angry": (0.85, 0.3), "afraid": (0.7, 0.35),
           "surprised": (0.75, 0.35), "tender": (0.4, 0.45), "sarcastic": (0.55, 0.4), "urgent": (0.75, 0.3), "whisper": (0.3, 0.5)}

# English voices only, tagged for casting. (Kokoro naming: a=American b=British, f/m gender)
VOICES: dict[str, dict] = {
    "af_heart":    {"gender": "female", "age": "adult",   "desc": "American, warm, clear — great narrator"},
    "af_bella":    {"gender": "female", "age": "young",   "desc": "American, bright, expressive"},
    "af_nicole":   {"gender": "female", "age": "young",   "desc": "American, soft, breathy"},
    "af_sarah":    {"gender": "female", "age": "adult",   "desc": "American, even, professional"},
    "af_sky":      {"gender": "female", "age": "young",   "desc": "American, light, youthful"},
    "af_nova":     {"gender": "female", "age": "adult",   "desc": "American, confident"},
    "af_aoede":    {"gender": "female", "age": "adult",   "desc": "American, smooth"},
    "af_kore":     {"gender": "female", "age": "adult",   "desc": "American, measured"},
    "af_jessica":  {"gender": "female", "age": "young",   "desc": "American, casual"},
    "af_river":    {"gender": "female", "age": "adult",   "desc": "American, low, calm"},
    "af_alloy":    {"gender": "female", "age": "adult",   "desc": "American, neutral"},
    "bf_emma":     {"gender": "female", "age": "adult",   "desc": "British, refined — period narrator"},
    "bf_isabella": {"gender": "female", "age": "adult",   "desc": "British, gentle"},
    "bf_alice":    {"gender": "female", "age": "young",   "desc": "British, crisp"},
    "bf_lily":     {"gender": "female", "age": "young",   "desc": "British, sweet"},
    "am_adam":     {"gender": "male",   "age": "adult",   "desc": "American, deep, steady"},
    "am_michael":  {"gender": "male",   "age": "adult",   "desc": "American, friendly"},
    "am_fenrir":   {"gender": "male",   "age": "adult",   "desc": "American, gravelly"},
    "am_eric":     {"gender": "male",   "age": "adult",   "desc": "American, plain"},
    "am_liam":     {"gender": "male",   "age": "young",   "desc": "American, youthful"},
    "am_onyx":     {"gender": "male",   "age": "elderly", "desc": "American, very deep, older"},
    "am_puck":     {"gender": "male",   "age": "young",   "desc": "American, playful"},
    "am_echo":     {"gender": "male",   "age": "adult",   "desc": "American, resonant"},
    "bm_george":   {"gender": "male",   "age": "elderly", "desc": "British, distinguished, older"},
    "bm_daniel":   {"gender": "male",   "age": "adult",   "desc": "British, composed"},
    "bm_lewis":    {"gender": "male",   "age": "adult",   "desc": "British, warm"},
    "bm_fable":    {"gender": "male",   "age": "young",   "desc": "British, storyteller"},
}
DEFAULT_NARRATOR = "af_heart"
CAPS_WORD = re.compile(r"\b[A-Z]{2,}\b")
KEEP_CAPS = {"OK", "TV", "USA", "UK", "US", "FBI", "CIA", "NASA", "BBC", "ID", "DNA", "PS", "AM", "PM", "MP", "RSVP"}


def normalize_for_tts(text: str) -> str:
    """Drop-caps ('IT is a truth') and shouted words ('I will NOT') get spelled out letter by letter
    by the phonemizer. Lowercase them (capitalise if at sentence start)."""
    def fix(m):
        w = m.group(0)
        if w in KEEP_CAPS:
            return w
        start = m.start() == 0 or text[max(0, m.start() - 2):m.start()].strip()[-1:] in ("", ".", "!", "?", "“", '"')
        return w.capitalize() if start else w.lower()
    text = CAPS_WORD.sub(fix, text)
    text = re.sub(r"\s*[—–]\s*", ", ", text)                # dashes read better as short pauses
    return re.sub(r"\s+,", ",", re.sub(r",\s*,", ",", text)).strip()
SPEED = {"neutral": 1.0, "happy": 1.05, "sad": 0.92, "angry": 1.08, "afraid": 1.05, "surprised": 1.05,
         "tender": 0.93, "sarcastic": 0.97, "urgent": 1.12, "whisper": 0.9}


def pick_voice(character: dict, taken: set[str], narrator: str, british: bool = False) -> str:
    """Rule-based casting: match gender+age, prefer unused voices, prefer accent family of narrator."""
    g, a = character.get("gender", "unknown"), character.get("age", "unknown")
    cands = [v for v in VOICES if v != narrator]
    def score(v):
        m = VOICES[v]; s = 0
        s += 4 if m["gender"] == g else (1 if g == "unknown" else -6)
        s += 2 if m["age"] == a else (1 if a == "unknown" or m["age"] == "adult" else 0)
        s += 2 if (v.startswith("b") == british) else 0
        s -= 5 if v in taken else 0
        return s
    return max(cands, key=score)


class TTS:
    def __init__(self):
        from kokoro_onnx import Kokoro
        self.k = Kokoro(str(MODEL_DIR / "kokoro-v1.0.onnx"), str(MODEL_DIR / "voices-v1.0.bin"))
        self.lock = threading.Lock()
        AUDIO_DIR.mkdir(parents=True, exist_ok=True); PROMPT_DIR.mkdir(parents=True, exist_ok=True)
        self._cb_ok, self._cb_checked = False, 0.0

    def chatterbox_available(self) -> bool:
        """Probe the expressive-dialogue worker at most every 15s."""
        import time
        if time.time() - self._cb_checked < 15:
            return self._cb_ok
        self._cb_checked = time.time()
        try:
            with urllib.request.urlopen(CHATTERBOX_URL + "/health", timeout=1.5) as r:
                self._cb_ok = bool(json.load(r).get("ok"))
        except Exception:
            self._cb_ok = False
        return self._cb_ok

    def prompt_for(self, voice: str) -> Path:
        """Reference clip for Chatterbox voice-matching, rendered once per Kokoro voice."""
        p = PROMPT_DIR / f"{voice}.wav"
        if not p.exists():
            lang = "en-gb" if voice.startswith("b") else "en-us"
            with self.lock:
                samples, sr = self.k.create(PROMPT_TEXT, voice=voice, speed=1.0, lang=lang)
            sf.write(str(p), np.asarray(samples, dtype=np.float32), sr, subtype="PCM_16")
        return p

    @staticmethod
    def key(text: str, voice: str, speed: float) -> str:
        return hashlib.sha1(f"{voice}|{speed:.2f}|{text}".encode()).hexdigest()[:20]

    def synth(self, text: str, voice: str, emotion: str = "neutral", dialogue: bool = False) -> tuple[str, float]:
        """Returns (audio filename, duration seconds). Cached. Dialogue goes to Chatterbox when the worker is up."""
        speed = SPEED.get(emotion, 1.0)
        text = normalize_for_tts(text)
        use_cb = dialogue and self.chatterbox_available()
        k = self.key(("cb|" + emotion + "|" if use_cb else "") + text, voice, speed)
        out = AUDIO_DIR / f"{k}.wav"
        if out.exists():
            info = sf.info(str(out)); return out.name, info.duration
        if use_cb:
            ex, cfg = EXPRESS.get(emotion, EXPRESS["neutral"])
            body = json.dumps({"text": text, "prompt": str(self.prompt_for(voice)), "exaggeration": ex, "cfg_weight": cfg}).encode()
            req = urllib.request.Request(CHATTERBOX_URL + "/synth", data=body, headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                samples, sr = sf.read(io.BytesIO(r.read()), dtype="float32")
        else:
            lang = "en-gb" if voice.startswith("b") else "en-us"
            with self.lock:
                samples, sr = self.k.create(text, voice=voice, speed=speed, lang=lang)
        samples = np.asarray(samples, dtype=np.float32)
        pad = np.zeros(int(sr * 0.25), dtype=np.float32)      # small breath gap between segments
        samples = np.concatenate([samples, pad])
        tmp = out.with_suffix(".tmp.wav")
        sf.write(str(tmp), samples, sr, subtype="PCM_16")
        tmp.rename(out)
        return out.name, len(samples) / sr
