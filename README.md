<p align="center"><img src="docs/icon.svg" width="88" alt=""></p>
<h1 align="center">AnyVoice</h1>
<p align="center"><b>Drop a book. Hear the cast.</b><br>
Turns any epub / pdf / txt into a full-cast audiobook — characters detected and voiced automatically — and starts playing on your phone while the rest renders. Runs on your own machine.</p>
<p align="center"><a href="https://surajtripathi.info/anyvoice-audiobooks/">Website</a> · <a href="#quick-start">Quick start</a> · <a href="#how-it-works">How it works</a> · <a href="CONTRIBUTING.md">Contributing</a> · MIT</p>

---

<p align="center"><img src="docs/screenshots/player.jpg" width="780" alt="AnyVoice player: chapters with render progress, export panel, and the now-playing bar showing the speaking character"></p>

## What it does

- **Reads the book** — epub, pdf or plain text → clean chapters (Gutenberg drop-caps, captions and page numbers handled).
- **Casts it** — an LLM works out who speaks every line, discovers characters as they appear, tags emotion and the scene. Each character gets a distinct voice matched to gender and age. No key? A regex fallback does a rough job.
- **Voices it locally** — [Kokoro-82M](https://github.com/hexgrad/kokoro) for narration (~4× realtime on an M1 Max, 27 English voices). Optional [Chatterbox](https://github.com/resemble-ai/chatterbox) re-renders dialogue expressively in the background — angry lines sound angry.
- **Plays immediately** — first audio in ~15 s; the pipeline stays ahead of you, chapter by chapter, from wherever you are listening.
- **Lets you recast** — don't like Mr. Darcy? Pick another voice; only his lines re-render, starting from your position.
- **Exports** — a real `.m4b` audiobook with chapter markers and title/author tags, or any chapter as mp3, with or without the ambience mixed in.
- **Sets the scene** — subtle procedural background sound (rain, thunder, hearth, carriage, ballroom murmur…) that follows the text. Off / low / mid. Nothing sampled, nothing to license.
- **Phone-first** — open it on your phone over Wi-Fi, add to home screen, lock-screen controls, resume where you left off.

Cost: **$0** for voices. The LLM casting is ~$1 per novel with Claude Opus 5, less with Kimi K3 or Sonnet. Your books never leave your machine except the text sent to the LLM for casting.

## Quick start

Requires Python 3.10+ with [uv](https://docs.astral.sh/uv/), `ffmpeg`, and ~400 MB for the Kokoro model.

```bash
git clone https://github.com/surajtripathy07/anyvoice-audiobooks && cd anyvoice-audiobooks
uv sync
mkdir -p models && cd models && \
  curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx && \
  curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin && cd ..
cp .env.example .env        # add ONE LLM key (see below) — optional but strongly recommended
./run.sh                    # → http://localhost:8080   phone: http://<your-mac-ip>:8080
```

Drop an epub on the page. Public-domain books from [Project Gutenberg](https://www.gutenberg.org/ebooks/1342) are perfect for a first try.

### LLM key (casting quality)

| Provider | `.env` | Default model | ~Cost / novel |
|---|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY=` | `claude-opus-5` | $1.50 |
| OpenRouter (Kimi K3 etc.) | `OPENROUTER_API_KEY=` + `LLM_PROVIDER=openrouter` | `moonshotai/kimi-k3` | $0.90 |
| OpenAI | `OPENAI_API_KEY=` + `LLM_PROVIDER=openai` | `gpt-5.4-mini` | $0.30 |

Override with `LLM_MODEL=`. The header chip in the app shows what's active. Without a key you get heuristic casting: fine for `"…," said Elizabeth`, weak on long untagged exchanges, and every line is read as neutral.

### Expressive dialogue (optional)

```bash
engines/chatterbox/run.sh   # separate process on :8091; downloads ~3 GB once; Apple Silicon or CUDA recommended
```

When it's up, the app renders everything with Kokoro first (so you can listen right away), then re-renders dialogue near your position with Chatterbox and swaps it in. ~0.5× realtime on an M1 Max, so it trails you by a few minutes rather than blocking.

## How it works

```
book ──ingest──▶ chapters ──segment──▶ [narration | “quote”] units, numbered
                                              │
                         LLM: {speaker, emotion} per quote + new characters + scenes
                                              │
              cast: character → voice (gender/age matched, distinct, swappable)
                                              │
        Kokoro (all lines, fast) ──▶ Chatterbox upgrade (dialogue, expressive) ──▶ cache
                                              │
                    player streams segments as they land · ambience mixed in-browser
```

The LLM never echoes the book: it receives the chapter with quotes tagged `[Q12]` and paragraphs tagged `[P3]`, and returns only labels. That keeps casting at ~30k output tokens per novel. Audio is cached by `(text, voice, engine, emotion)` so swaps and re-runs are instant when nothing changed.

Details and a map of the code: [CONTRIBUTING.md](CONTRIBUTING.md).

## Status

A few days old. Tested end-to-end on *Pride and Prejudice* (63 chapters). PDF extraction is heuristic and untested on real-world novels; single-quote dialogue is not yet split. Issues and PRs welcome — the "good first contributions" list is in CONTRIBUTING.

## Related projects

Good tools already exist; the difference is that they make audiobook *files* and AnyVoice is an audiobook *app* — casting runs a chapter ahead of you and you listen while it renders.

- [ebook2audiobook](https://github.com/DrewThomasson/ebook2audiobook) — the category leader: single narrator, voice cloning, 1,000+ languages, many engines.
- [audiblez](https://github.com/santinic/audiblez), [abogen](https://github.com/denizsafak/abogen) — one-command Kokoro → `.m4b` (abogen adds synced captions).
- [alexandria-audiobook](https://github.com/Finrandojin/alexandria-audiobook) — multi-voice studio: LLM script annotation, voice cloning/design, LoRA, per-line direction. If you want to *produce* an audiobook, use that.
- [audiobook-creator](https://github.com/prakharsr/audiobook-creator), [VoxNovel](https://github.com/DrewThomasson/VoxNovel) — earlier multi-voice batch converters (LLM / BookNLP attribution).
- [tts-audiobook-tool](https://github.com/zeropointnine/tts-audiobook-tool) — many engines, synced reader; dialogue gets a separate voice but not per character.

## Copyright, plainly

AnyVoice converts books *you* have for *your* listening, on your hardware, like a screen reader. It stores nothing outside your machine and shares nothing. Don't redistribute the audio it makes from copyrighted books. Public-domain works are fair game for anything.

## License

MIT © 2026 Suraj Tripathi. Kokoro is Apache-2.0; Chatterbox is MIT.
