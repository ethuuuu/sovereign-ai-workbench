"""Extraction and clause-aware chunking. Pure Python, no lxml.

Deliberately avoids python-docx here. python-docx imports lxml, and lxml
has not declared itself safe without the GIL, so importing it would turn
the GIL back on for the whole ingest process and undo the parallelism
(see agent/parallel.py). A .docx is a zip of XML; stdlib handles it.

Chunking splits on headings and clause numbers first and only falls back
to token windows. An SOP clause is a semantic unit, and splitting one
mid-clause is how retrieval systems end up producing confident nonsense.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

TARGET_TOKENS = 800
OVERLAP_TOKENS = 100

_WORD = re.compile(r"\w+")
_CLAUSE = re.compile(r"^\s{0,8}(\d+(?:\.\d+){0,3})[.)]?\s+(\S.*)$")
_HEADING = re.compile(r"^\s{0,4}([A-Z][A-Z0-9 ,/&().-]{4,80})\s*$")
_DOCX_TEXT = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".log", ".rst"}
SUPPORTED = TEXT_SUFFIXES | {".pdf", ".docx"}


@dataclass
class Chunk:
    id: str
    text: str
    source: str
    page: int
    section: str
    tokens: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "source": self.source,
            "page": self.page,
            "section": self.section,
            "tokens": self.tokens,
        }


@dataclass
class Page:
    number: int
    text: str


@dataclass
class Extraction:
    path: Path
    pages: list[Page] = field(default_factory=list)
    method: str = "text"
    error: str | None = None
    needs_ocr: list[int] = field(default_factory=list)


def tokens(text: str) -> int:
    return len(_WORD.findall(text))


def extract(path: Path) -> Extraction:
    suffix = path.suffix.lower()
    try:
        if suffix in TEXT_SUFFIXES:
            return Extraction(
                path, [Page(1, path.read_text(encoding="utf-8", errors="replace"))]
            )
        if suffix == ".docx":
            return Extraction(path, [Page(1, _docx_text(path))], method="docx-zip")
        if suffix == ".pdf":
            return _pdf(path)
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop a run
        return Extraction(path, [], error=f"{type(exc).__name__}: {exc}")
    return Extraction(path, [], error=f"unsupported suffix '{suffix}'")


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    return "\n".join(node.text for node in root.iter(_DOCX_TEXT) if node.text)


def _pdf(path: Path) -> Extraction:
    try:
        import pdfplumber
    except ImportError:
        return Extraction(path, [], error="pdfplumber not installed")

    pages, needs_ocr = [], []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if len(text) < 20:
                needs_ocr.append(number)
            pages.append(Page(number, text))
    return Extraction(path, pages, method="pdfplumber", needs_ocr=needs_ocr)


def chunk_extraction(extraction: Extraction) -> list[Chunk]:
    """The CPU-bound half of ingest, and the part worth parallelising."""
    out: list[Chunk] = []
    for page in extraction.pages:
        out.extend(_chunk_page(extraction.path, page))
    return out


def _chunk_page(path: Path, page: Page) -> list[Chunk]:
    units: list[tuple[str, str]] = []
    section = ""
    buffer: list[str] = []

    for line in page.text.splitlines():
        heading = _HEADING.match(line)
        clause = _CLAUSE.match(line)
        if heading:
            if buffer:
                units.append((section, "\n".join(buffer)))
                buffer = []
            section = heading.group(1).strip()
            continue
        if clause and buffer:
            units.append((section, "\n".join(buffer)))
            buffer = []
        if line.strip():
            buffer.append(line.rstrip())
    if buffer:
        units.append((section, "\n".join(buffer)))

    chunks: list[Chunk] = []
    current: list[str] = []
    current_tokens = 0
    current_section = section

    def flush() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        text = "\n".join(current).strip()
        if text:
            digest = hashlib.sha1(
                f"{path}:{page.number}:{text}".encode()
            ).hexdigest()[:12]
            chunks.append(
                Chunk(digest, text, str(path), page.number, current_section,
                      tokens(text))
            )
        keep: list[str] = []
        kept = 0
        for line in reversed(current):
            n = tokens(line)
            if kept + n > OVERLAP_TOKENS:
                break
            keep.insert(0, line)
            kept += n
        current = keep
        current_tokens = kept

    for unit_section, body in units:
        n = tokens(body)
        if current_tokens + n > TARGET_TOKENS and current:
            flush()
        current_section = unit_section or current_section
        current.append(body)
        current_tokens += n

    current_tokens = 0 if not current else current_tokens
    if current:
        text = "\n".join(current).strip()
        if text:
            digest = hashlib.sha1(
                f"{path}:{page.number}:{text}".encode()
            ).hexdigest()[:12]
            chunks.append(
                Chunk(digest, text, str(path), page.number, current_section,
                      tokens(text))
            )
    return chunks


def process(path: Path) -> tuple[list[Chunk], str | None]:
    extraction = extract(path)
    if extraction.error:
        return [], f"{path.name}: {extraction.error}"
    chunks = chunk_extraction(extraction)
    note = None
    if extraction.needs_ocr:
        note = (
            f"{path.name}: pages {extraction.needs_ocr} yielded almost no text "
            "and are probably scans; OCR escalation is still TODO"
        )
    return chunks, note
