"""Deterministic splitting of chapter text into attribution units (quotes vs narration)
and TTS-sized segments. The LLM only ever labels quote units by id, keeping its output tiny."""
from __future__ import annotations
import re
from dataclasses import dataclass

QUOTE_RE = re.compile(r'“[^”]*”|"[^"]*"|‘[^’]*’(?=\s|[,.!?;:]|$)')
SENT_RE = re.compile(r"(?:(?<=[.!?…])|(?<=[.!?…][\"”’']))\s+(?=[\"“‘A-Z0-9])")
MAX_SEG_CHARS = 420


@dataclass
class Unit:
    id: int
    kind: str      # "quote" | "narr"
    text: str
    para: int


def split_units(text: str) -> list[Unit]:
    """Split into alternating narration/quote units, numbered, paragraph-aware."""
    units: list[Unit] = []
    uid = 0
    for pi, para in enumerate(p for p in text.split("\n") if p.strip()):
        pos = 0
        for m in QUOTE_RE.finditer(para):
            if m.start() > pos:
                narr = para[pos:m.start()].strip()
                if narr:
                    units.append(Unit(uid, "narr", narr, pi)); uid += 1
            q = m.group(0).strip()
            if len(q) > 2:
                units.append(Unit(uid, "quote", q, pi)); uid += 1
            pos = m.end()
        tail = para[pos:].strip()
        if tail:
            units.append(Unit(uid, "narr", tail, pi)); uid += 1
    return units


def render_for_llm(units: list[Unit]) -> str:
    """Chapter text with quote units tagged as [Q<id>] for the model to label."""
    out, last_para = [], -1
    for u in units:
        if u.para != last_para:
            out.append(f"\n[P{u.para}]"); last_para = u.para
        out.append(f" [Q{u.id}]{u.text}" if u.kind == "quote" else " " + u.text)
    return "".join(out).strip()


def chunk_for_tts(text: str, limit: int = MAX_SEG_CHARS) -> list[str]:
    """Split a long unit into TTS-friendly pieces on sentence boundaries."""
    text = text.strip()
    if len(text) <= limit:
        return [text]
    pieces, buf = [], ""
    for s in SENT_RE.split(text):
        if len(buf) + len(s) + 1 > limit and buf:
            pieces.append(buf.strip()); buf = s
        else:
            buf = f"{buf} {s}".strip()
        while len(buf) > limit:   # pathological long sentence: hard split on commas/spaces
            cut = buf.rfind(", ", 0, limit) + 1 or buf.rfind(" ", 0, limit)
            cut = cut if cut > 40 else limit
            pieces.append(buf[:cut].strip()); buf = buf[cut:].strip()
    if buf:
        pieces.append(buf.strip())
    return pieces
