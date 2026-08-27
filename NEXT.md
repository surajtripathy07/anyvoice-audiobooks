# AnyVoice — where we are (27 Aug 2026)

## Restart
```
./run.sh                          # main app  -> http://<mac-ip>:8080 (phone on same Wi-Fi)
engines/chatterbox/run.sh         # expressive dialogue worker on :8091 (optional; finishes its ~3 GB model download on first start)
```
Book already loaded: Pride and Prejudice (63 chapters, heuristic-cast). Position resumes from the phone (localStorage).

## Works today
- epub/pdf/txt -> chapters -> quote/narration units -> cast -> Kokoro (4x realtime on M1 Max) -> streaming player
- Cast panel: per-character voice swap with preview; only that character's lines re-render, from the current line outward
- Lock-screen controls, resume, speed, line-level progress

## Blocked: no working LLM key
- `dev-assist/.env` Anthropic key -> 401 invalid; OpenAI key -> account has no credits
- Add ONE to `.env` (see README) and restart. Then re-upload the book so it gets LLM casting (heuristic is rough on untagged dialogue, and marks every line `neutral` -> no emotion).

## Suraj's feedback while listening
1. Narrator (af_heart) is good. Character voices are bland / emotionless -> Chatterbox for dialogue (wired in `tts.py`, worker in `engines/chatterbox/`, untested: model download was still in progress). Emotion labels need the LLM.
2. "IT is a truth" read as "I T" -> fixed (`normalize_for_tts`), affected lines invalidated.
3. Narrator voice changed mid-listen -> that was my swap test; reverted to af_heart.
4. Wants scene ambience: rain/thunder/street chatter/hearth etc., low and never overpowering; free music where sensible.
   Plan: LLM emits per-scene {start_line, ambience, mood}; CC0/procedural loops; mixed client-side (Web Audio, ~-20 dB, 3-4 s crossfade, user slider). Half a day. Needs the LLM key.

## Next session, in order
1. Get a key in, re-upload P&P, listen to LLM casting quality.
2. Finish Chatterbox: `tail logs/chatterbox.log` until "chatterbox loaded", check `curl :8091/health`, then confirm dialogue lines render via it (cache key prefix `cb|`) and measure x-realtime on MPS. If < 1x, keep Kokoro for long lines and Chatterbox for short ones.
3. Ambience layer (above).
4. Speed: try mlx-audio Kokoro (Apple Silicon native) — likely 5x faster than ONNX.
5. PDF path untested on a real novel PDF.

## Gotcha found at shutdown
`uv init` inside `engines/chatterbox` made it a **workspace member** of the main project, so Chatterbox + torch 2.13 were
installed into the main `.venv` (Python 3.14) — and it imported fine there. Both `./run.sh` and `engines/chatterbox/run.sh`
use that single venv. Fine for now; if torch/3.14 misbehaves, remove the `[tool.uv.workspace]` block from `pyproject.toml`
and `uv sync` inside `engines/chatterbox` to get its own 3.12 env.
