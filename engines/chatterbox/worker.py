"""Chatterbox TTS worker — expressive dialogue voices. Runs in its own Python 3.12 env on :8091.
POST /synth {text, prompt, exaggeration, cfg_weight} -> WAV bytes.  `prompt` = path to a reference wav
(we use Kokoro-rendered samples so each character keeps the voice it was cast with)."""
import io, os, threading, time
import torch, soundfile as sf
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel

DEV = "mps" if torch.backends.mps.is_available() else "cpu"
_orig = torch.load
def _patched(*a, **k):
    k.setdefault("map_location", torch.device(DEV)); return _orig(*a, **k)
torch.load = _patched
from chatterbox.tts import ChatterboxTTS

app = FastAPI()
model = None
lock = threading.Lock()


@app.on_event("startup")
def load():
    global model
    t = time.time(); model = ChatterboxTTS.from_pretrained(device=DEV); print(f"chatterbox loaded on {DEV} in {time.time()-t:.1f}s", flush=True)


class Req(BaseModel):
    text: str
    prompt: str
    exaggeration: float = 0.5
    cfg_weight: float = 0.5


@app.get("/health")
def health():
    return {"ok": model is not None, "device": DEV}


@app.post("/synth")
def synth(r: Req):
    with lock:
        wav = model.generate(r.text, audio_prompt_path=r.prompt, exaggeration=r.exaggeration, cfg_weight=r.cfg_weight)
    buf = io.BytesIO(); sf.write(buf, wav.squeeze().cpu().numpy(), model.sr, format="WAV", subtype="PCM_16")
    return Response(buf.getvalue(), media_type="audio/wav")
