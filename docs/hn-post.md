# Show HN draft — paste at https://news.ycombinator.com/submit

**Title** (78 chars max, HN trims at 80):

Show HN: AnyVoice – full-cast audiobooks from any epub, rendered locally

**URL:** https://github.com/surajtripathy07/anyvoice-audiobooks

**First comment** (post this yourself right after submitting — HN readers expect the author's context):

I got tired of single-voice TTS for ebooks, so I built a small tool that turns an epub/pdf/txt into a *full-cast* audiobook and starts playing on my phone within ~15 seconds while the rest renders.

How it works: the book is split into narration and quoted units; an LLM labels who speaks each quote (it only returns labels, never the text — ~30k output tokens for a whole novel, about $1 with Opus 5, less with Kimi K3/Sonnet). Each character gets a distinct voice matched to gender/age. Narration is Kokoro-82M locally (~4x realtime on an M1 Max). Optionally Chatterbox re-renders dialogue expressively in the background and swaps it in — it's ~0.5x realtime on Apple Silicon so it trails you rather than blocking. Don't like a voice? Swap it and only that character's lines re-render, from where you're listening.

There's also subtle scene ambience (rain, thunder, hearth, carriage, ballroom murmur) synthesized procedurally from filtered noise so there's nothing to license; the LLM tags scene changes per paragraph.

Honest state: a few days old. Tested end to end on Pride and Prejudice. PDF handling is heuristic. Without an LLM key it falls back to regex speech-tag heuristics, which are rough on long untagged exchanges. Everything runs on your machine; only the chapter text goes to the LLM for casting. MIT.

Things I'd love input on: better open expressive TTS at near-realtime on consumer hardware, and whether anyone has a good approach to attributing long unattributed dialogue runs without a frontier model.
