"""Procedural ambience loops (no samples, no licensing): filtered noise + simple event models.
Rendered once to data/ambience/<name>.ogg (30 s, seamless), mixed client-side under the voices."""
from __future__ import annotations
import subprocess
from pathlib import Path
import numpy as np

AMB_DIR = Path(__file__).resolve().parent.parent / "data" / "ambience"
SR, SECS = 22050, 30
AMBIENCES = ["rain", "thunderstorm", "wind", "hearth", "night", "sea", "countryside", "street", "ballroom", "carriage", "forest"]
MOODS = ["none", "tense", "warm", "melancholy", "playful", "romantic"]


def _rng(name): return np.random.default_rng(abs(hash(name)) % (2**32))
def _noise(n, rng): return rng.standard_normal(n).astype(np.float32)

def _lowpass(x, cutoff, sr=SR):
    from scipy.signal import lfilter
    a = np.exp(-2 * np.pi * cutoff / sr)
    return lfilter([1 - a], [1, -a], x).astype(np.float32)

def _bandpass(x, lo, hi): return _lowpass(x, hi) - _lowpass(x, lo)

def _env_noise(n, rng, rate_hz, depth):
    """slow random amplitude modulation (gusts, swells)"""
    k = max(2, int(n * rate_hz / SR)); pts = rng.uniform(1 - depth, 1, k + 2)
    return np.interp(np.arange(n), np.linspace(0, n, k + 2), pts).astype(np.float32)

def _events(n, rng, per_sec, gen):
    y = np.zeros(n, np.float32); t = 0.0
    while t < SECS:
        t += rng.exponential(1 / per_sec); i = int(t * SR)
        if i >= n: break
        e = gen(rng); y[i:i + len(e)] += e[:n - i]
    return y

def _thunder(rng):
    L = int(rng.uniform(2.5, 5) * SR); x = _lowpass(_noise(L, rng), rng.uniform(60, 140))
    env = np.exp(-np.linspace(0, rng.uniform(3, 6), L)) * (1 + 0.6 * np.sin(np.linspace(0, rng.uniform(4, 10), L)) ** 2)
    return (x * env * 9).astype(np.float32)

def _crackle(rng):
    L = int(rng.uniform(0.004, 0.02) * SR); return (_noise(L, rng) * np.exp(-np.linspace(0, 8, L)) * rng.uniform(0.3, 1.2)).astype(np.float32)

def _chirp(rng, f0=4200, dur=0.06, reps=3):
    L = int(dur * SR); t = np.arange(L) / SR; one = np.sin(2 * np.pi * f0 * t) * np.sin(np.pi * t / dur) ** 2
    gap = np.zeros(int(0.05 * SR), np.float32); return (np.concatenate([one, gap] * reps) * 0.25).astype(np.float32)

def _bird(rng):
    L = int(rng.uniform(0.15, 0.4) * SR); t = np.arange(L) / SR; f = rng.uniform(1800, 3500) * (1 + 0.3 * np.sin(2 * np.pi * rng.uniform(4, 12) * t))
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * t / t[-1]) * rng.uniform(0.15, 0.4)).astype(np.float32)

def _clop(rng):
    L = int(0.08 * SR); return (_bandpass(_noise(L, rng), 300, 1200) * np.exp(-np.linspace(0, 12, L)) * 1.5).astype(np.float32)

def _babble(n, rng, voices=14):
    """crowd murmur: many overlapping band-passed noise 'syllables' — unintelligible by construction"""
    y = np.zeros(n, np.float32)
    for v in range(voices):
        f = rng.uniform(180, 320) * (1.6 if v % 3 == 0 else 1.0)
        def syl(r, f=f):
            L = int(r.uniform(0.08, 0.25) * SR); return (_bandpass(_noise(L, r), f, f * 6) * np.sin(np.pi * np.arange(L) / L) * 0.5).astype(np.float32)
        y += _events(n, rng, rng.uniform(2, 4), syl) * rng.uniform(0.3, 1.0)
    return _lowpass(y, 2500) / voices * 3

def _wave(rng):
    L = int(rng.uniform(4, 8) * SR); t = np.linspace(0, 1, L)
    env = np.sin(np.pi * t) ** 1.5 * (0.7 + 0.3 * np.sin(np.pi * t * 3) ** 2)
    return (_bandpass(_noise(L, rng), 150, 3000) * env * 1.2).astype(np.float32)


def render(name: str) -> np.ndarray:
    rng, n = _rng(name), SR * SECS
    if name == "rain":
        return _bandpass(_noise(n, rng), 400, 6000) * _env_noise(n, rng, 0.3, 0.25) * 0.5
    if name == "thunderstorm":
        return render("rain") * 1.1 + _events(n, rng, 1 / 9, _thunder) + _lowpass(_noise(n, rng), 90) * _env_noise(n, rng, 0.2, 0.8) * 2
    if name == "wind":
        return _bandpass(_noise(n, rng), 80, 700) * _env_noise(n, rng, 0.25, 0.7) * 1.4
    if name == "hearth":
        return _lowpass(_noise(n, rng), 250) * _env_noise(n, rng, 0.6, 0.4) * 0.9 + _events(n, rng, 9, _crackle)
    if name == "night":
        return _events(n, rng, 1.4, _chirp) + _lowpass(_noise(n, rng), 120) * 0.2 + _events(n, rng, 0.9, lambda r: _chirp(r, 3600, 0.05, 5))
    if name == "sea":
        return _events(n, rng, 1 / 5, _wave) + _bandpass(_noise(n, rng), 100, 1500) * 0.15
    if name == "countryside":
        return render("wind") * 0.35 + _events(n, rng, 0.7, _bird)
    if name == "forest":
        return _bandpass(_noise(n, rng), 200, 2500) * _env_noise(n, rng, 0.4, 0.6) * 0.5 + _events(n, rng, 0.35, _bird)
    if name == "street":
        return _babble(n, rng, 18) + _lowpass(_noise(n, rng), 200) * _env_noise(n, rng, 0.5, 0.6) * 0.8 + _events(n, rng, 0.6, _clop) * 0.5
    if name == "ballroom":
        return _babble(n, rng, 24) * 1.2 + _events(n, rng, 0.25, lambda r: _bird(r) * 0.3)   # murmur + faint high sparkle
    if name == "carriage":
        beat = np.zeros(n, np.float32); step = int(SR * 0.42)
        for i in range(0, n, step):
            c = _clop(rng); beat[i:i + len(c)] += c[:n - i]
            j = i + int(step * 0.5) + int(rng.uniform(-0.02, 0.02) * SR); c = _clop(rng) * 0.8
            if j < n: beat[j:j + len(c)] += c[:n - j]
        return beat * 0.8 + _lowpass(_noise(n, rng), 160) * _env_noise(n, rng, 1.5, 0.5) * 1.5
    raise ValueError(name)


def _seamless(x: np.ndarray, fade=2.0) -> np.ndarray:
    """crossfade the tail into the head so the loop point is inaudible"""
    k = int(fade * SR); w = np.linspace(0, 1, k, dtype=np.float32)
    head = x[:k] * w + x[-k:] * (1 - w)
    return np.concatenate([head, x[k:-k]])


def ensure_all() -> dict[str, str]:
    AMB_DIR.mkdir(parents=True, exist_ok=True); out = {}
    import soundfile as sf
    for name in AMBIENCES:
        ogg, wav = AMB_DIR / f"{name}.ogg", AMB_DIR / f"{name}.wav"
        if not wav.exists():                      # wav kept for export mixing
            x = _seamless(render(name)); x = x / (np.max(np.abs(x)) + 1e-6) * 0.8
            sf.write(str(wav), x.astype(np.float32), SR, subtype="PCM_16")
        if not ogg.exists():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libopus", "-b:a", "48k", str(ogg)], check=True)
        out[name] = ogg.name
    return out


if __name__ == "__main__":
    import time; t = time.time(); print(ensure_all(), f"{time.time()-t:.1f}s")
