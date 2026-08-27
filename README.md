# AnyVoice — full-cast audiobooks from any book

Drop an **epub / pdf / txt**, and AnyVoice finds the characters, casts a distinct voice for each,
and starts streaming the audiobook to your phone while the rest renders in the background.
Everything runs on your Mac; the only paid piece is the LLM that works out who is speaking (~$1/book).

## Run

```bash
./run.sh                # http://localhost:8080  — phone: http://<mac-ip>:8080 on the same Wi-Fi
```

One-time setup (models are not in git):

```bash
uv sync
mkdir -p models && cd models
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

Rendering is ~4× realtime on an M1 Max. For expressive character dialogue also start the Chatterbox worker
(`engines/chatterbox/run.sh`, first start downloads ~3 GB); the app uses it automatically when it is up.

## LLM key (recommended — the heuristic fallback is rough on unattributed dialogue)

Put ONE of these in `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...          # default model claude-opus-5
OPENROUTER_API_KEY=sk-or-...          # + LLM_PROVIDER=openrouter  (default model moonshotai/kimi-k3)
OPENAI_API_KEY=sk-...                 # + LLM_PROVIDER=openai      (default model gpt-5.4-mini)
LLM_MODEL=...                         # optional override
```

Restart `./run.sh`. New uploads use the LLM; the header chip shows which model is active.
Without any key the app still works using regex speech-tag heuristics (`anyvoice/heuristic.py`).

## How it works

```
ingest.py      epub/pdf/txt -> chapters                (ebooklib / PyMuPDF)
segmenter.py   chapter -> numbered quote/narration units, TTS-sized chunks
llm.py         units -> {speaker, emotion} per quote + new characters   (Claude / OpenAI / OpenRouter)
heuristic.py   same, without an LLM
tts.py         Kokoro-82M (ONNX, local) + voice bank + rule-based casting; audio cached by hash
pipeline.py    per-book threads: attribute one chapter ahead, synthesize from the listening position
server.py      FastAPI: upload, state, voice swap, audio
static/        the player (PWA-ish: lock-screen controls, resume, speed, cast panel)
```

Voice swap = pick a new voice in **Cast**; only that character's lines re-render, starting from where you are.

## Data

`data/books/<id>/` holds `book.json` (state) + `chapters.json` (text). `data/audio/` is the segment cache
(WAV, keyed by voice+speed+text) — safe to delete; it just re-renders.
