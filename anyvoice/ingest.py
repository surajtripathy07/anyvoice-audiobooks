"""Book loading: epub / pdf / txt -> ordered chapters of plain text."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path

CHAPTER_RE = re.compile(
    r"^\s*(chapter|part|book|prologue|epilogue|letter)\b[^\n]{0,80}$|^\s*([IVXLC]+|\d{1,3})\.?\s*$",
    re.I | re.M,
)
MIN_WORDS = 150          # drop TOC / title pages / license stubs
TARGET_CHUNK_WORDS = 3000


@dataclass
class Chapter:
    title: str
    text: str
    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass
class Book:
    title: str
    author: str
    chapters: list[Chapter] = field(default_factory=list)


def load_book(path: str | Path) -> Book:
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".epub":
        return _load_epub(path)
    if ext == ".pdf":
        return _load_pdf(path)
    if ext in (".txt", ".md", ""):
        return _load_txt(path)
    raise ValueError(f"unsupported file type: {ext}")


# ---------------------------------------------------------------- epub
BLOCK_TAGS = ["h1", "h2", "h3", "p", "li", "blockquote", "div"]
HEAD_TAGS = {"h1", "h2", "h3"}


def _load_epub(path: Path) -> Book:
    import warnings
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup, NavigableString, XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

    bk = epub.read_epub(str(path), options={"ignore_ncx": True})
    title = (bk.get_metadata("DC", "title") or [("Untitled",)])[0][0]
    author = (bk.get_metadata("DC", "creator") or [("Unknown",)])[0][0]
    items = {it.get_id(): it for it in bk.get_items_of_type(ebooklib.ITEM_DOCUMENT)}
    order = [iid for iid, _ in bk.spine if iid in items] or list(items)

    chapters: list[Chapter] = []
    cur_title, cur_paras = "", []

    def flush():
        nonlocal cur_title, cur_paras
        text = "\n".join(cur_paras).strip()
        if len(text.split()) >= MIN_WORDS:
            chapters.append(Chapter(cur_title or f"Section {len(chapters)+1}", text))
        cur_paras = []

    for iid in order:
        soup = BeautifulSoup(items[iid].get_content(), "lxml")
        for t in soup(["script", "style", "nav", "sup", "table"]):
            t.decompose()
        for img in soup.find_all("img"):          # drop-cap images carry the letter in alt
            alt = (img.get("alt") or "").strip()
            img.replace_with(NavigableString(alt) if len(alt) == 1 else "")
        for sp in soup.find_all("span"):
            cls = " ".join(sp.get("class") or [])
            if "caption" in cls or "pageno" in cls or "page" in (sp.get("title") or "").lower():
                sp.decompose()
        body = soup.body or soup
        for el in body.find_all(BLOCK_TAGS):
            if el.name in HEAD_TAGS:
                flush()
                cur_title = _clean(el.get_text(" "))
                continue
            if el.find(BLOCK_TAGS):               # container, not a leaf block
                continue
            for br in el.find_all("br"):
                br.replace_with("\n")
            txt = _clean_para(el.get_text(""))
            if txt and not re.fullmatch(r"\[.*\]", txt):   # skip bracketed illustration credits

                cur_paras.append(txt)
    flush()
    return Book(title, author, _strip_gutenberg(chapters))


# ---------------------------------------------------------------- pdf
def _load_pdf(path: Path) -> Book:
    import pymupdf
    doc = pymupdf.open(str(path))
    pages = []
    for page in doc:
        t = page.get_text("text")
        # drop running headers/footers: very short first/last lines with digits
        lines = t.split("\n")
        if lines and re.fullmatch(r"\s*\d{1,4}\s*", lines[-1] or ""):
            lines = lines[:-1]
        if lines and len(lines[0]) < 60 and re.search(r"\d", lines[0]) and len(lines) > 3:
            lines = lines[1:]
        pages.append("\n".join(lines))
    raw = "\n".join(pages)
    raw = re.sub(r"-\n(\w)", r"\1", raw)            # de-hyphenate line breaks
    raw = re.sub(r"(?<![\.\!\?\"”’:])\n(?=[a-z,;])", " ", raw)  # join wrapped lines
    meta = doc.metadata or {}
    return Book(meta.get("title") or path.stem, meta.get("author") or "Unknown", _split_chapters(raw))


# ---------------------------------------------------------------- txt
def _load_txt(path: Path) -> Book:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return Book(path.stem.replace("_", " ").title(), "Unknown", _strip_gutenberg(_split_chapters(raw)))


# ---------------------------------------------------------------- helpers
def _split_chapters(raw: str) -> list[Chapter]:
    raw = _normalize(raw)
    marks = [m for m in CHAPTER_RE.finditer(raw)]
    chapters: list[Chapter] = []
    if len(marks) >= 3:
        for i, m in enumerate(marks):
            start = m.end()
            end = marks[i + 1].start() if i + 1 < len(marks) else len(raw)
            text = raw[start:end].strip()
            if len(text.split()) >= MIN_WORDS:
                chapters.append(Chapter(_clean(m.group(0)) or f"Chapter {len(chapters)+1}", text))
        if chapters:
            return chapters
    # fallback: fixed-size chunks on paragraph boundaries
    paras, buf, n = raw.split("\n\n"), [], 0
    for p in paras:
        buf.append(p); n += len(p.split())
        if n >= TARGET_CHUNK_WORDS:
            chapters.append(Chapter(f"Part {len(chapters)+1}", "\n\n".join(buf))); buf, n = [], 0
    if buf and (n >= MIN_WORDS or not chapters):
        chapters.append(Chapter(f"Part {len(chapters)+1}", "\n\n".join(buf)))
    return chapters


def _strip_gutenberg(chapters: list[Chapter]) -> list[Chapter]:
    out = []
    for c in chapters:
        t = c.text
        if "START OF THE PROJECT GUTENBERG" in t:
            t = t.split("***", 2)[-1] if t.count("***") >= 2 else t
        if "END OF THE PROJECT GUTENBERG" in t:
            t = t.split("*** END OF THE PROJECT GUTENBERG")[0]
        if re.search(r"project gutenberg", t, re.I) and len(t.split()) < 1500:
            continue  # license boilerplate chapter
        if len(t.split()) >= MIN_WORDS:
            out.append(Chapter(c.title, t.strip()))
    return out


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_para(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) > 1 else ""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()[:120]
