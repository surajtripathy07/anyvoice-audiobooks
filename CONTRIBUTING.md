# Contributing to AnyVoice

Thanks for wanting to help. AnyVoice is small on purpose — a few Python modules, one HTML file, no build step —
so most contributions are an afternoon's work. This page tells you where things live and what would help most.

## Dev setup

```bash
git clone https://github.com/surajtripathy07/anyvoice-audiobooks
cd anyvoice-audiobooks
uv sync                                   # Python deps (uv: https://docs.astral.sh/uv/)
mkdir -p models && cd models && \
  curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx && \
  curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin && cd ..
cp .env.example .env                      # add an LLM key (optional; heuristic casting works without one)
./run.sh                                  # http://localhost:8080
```

Optional expressive dialogue: `engines/chatterbox/run.sh` (downloads ~3 GB on first start; needs a GPU/Apple Silicon).

There is no test suite yet (see "Good first contributions"). Sanity-check a change by dropping a public-domain
epub from [Project Gutenberg](https://www.gutenberg.org/) and listening to the first chapter.

## Map of the code

| File | What it does | Touch it when |
|---|---|---|
| `anyvoice/ingest.py` | epub / pdf / txt → ordered chapters of clean text | a book comes out with wrong chapters, junk, or mangled paragraphs |
| `anyvoice/segmenter.py` | chapter → numbered quote/narration units → TTS-sized chunks | quotes are split wrong (nested quotes, single-quote dialogue, non-English quote marks) |
| `anyvoice/llm.py` | speaker attribution + character discovery + scene tagging via an LLM; provider adapter | adding a provider, improving the prompt/schema |
| `anyvoice/heuristic.py` | the no-LLM fallback (speech-tag regexes, pronoun/gender inference, keyword scenes) | making the free path smarter |
| `anyvoice/tts.py` | Kokoro wrapper, voice bank + rule-based casting, text normalisation, cache, Chatterbox routing | adding voices/engines, fixing pronunciation |
| `anyvoice/ambience.py` | procedural background-sound loops | adding or improving an ambience |
| `anyvoice/pipeline.py` | per-book worker threads: attribute ahead, synthesize from the listening position, upgrade pass, voice swaps | scheduling/priority, persistence |
| `server.py` | FastAPI routes | any new endpoint |
| `static/index.html` | the whole player UI (vanilla JS, no build) | UX |
| `engines/chatterbox/` | expressive-dialogue worker, its own process | swapping the dialogue engine |

Data lives in `data/` (git-ignored): `books/<id>/book.json` is the whole state of a book and is safe to inspect
or hand-edit while the server is stopped; `audio/` is a content-addressed cache you can delete any time.

## Good first contributions

- **Tests for `ingest` and `segmenter`** — fixture epubs/txt with known chapter counts and quote counts. This is the
  most valuable thing missing.
- **More quote styles** in `segmenter.py`: `‘single’` dialogue (common in UK editions), `«guillemets»`, em-dash
  dialogue (`— Like this, he said.`).
- **A real PDF novel** through `ingest._load_pdf` — headers/footers and hyphenation heuristics need real-world tuning.
- **Ambience loops** that sound better than mine (`ambience.py` is pure numpy; keep it license-free — no samples).
- **Music for `mood`** — the LLM already tags `tense / warm / melancholy / playful / romantic`; nothing plays yet.
  Needs a free-license source and a ducking strategy.
- **A local LLM path** (Ollama / Qwen) behind the same `LLM.attribute()` interface for a fully offline pipeline.
- **`mlx-audio` Kokoro** for Apple Silicon — probably several times faster than ONNX.
- **Faster expressive dialogue** — Chatterbox is ~0.5× realtime on an M1 Max; anything closer to realtime
  could replace the upgrade-pass design with direct rendering.

## Ground rules

- **No copyrighted audio or text in the repo.** Test with public-domain books only. Voices must be open models or
  consenting/public-domain references.
- Keep the UI a single dependency-free HTML file; keep the Python stdlib-first. If you need a dependency, say why in the PR.
- One PR = one change. Describe what you listened to and what changed.
- Commit messages: what + why in the body; the subject line should read like a changelog entry.

## Reporting a book that breaks

Open an issue with: the book's source (Gutenberg id or "my own epub, can't share"), what went wrong (chapters,
casting, a specific mispronunciation), and the `book.json` if you can share it. A 200-word excerpt that reproduces
the problem is the fastest path to a fix.
