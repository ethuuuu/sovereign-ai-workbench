"""Multimodal ingest: scanned PDFs, drawings, handwritten notes.

PHASE 2 -- interface final, pipeline partial. The two-stage decision is
the design that matters and it is documented here so it does not drift:

  OCR first, vision model second, and only when needed. Tesseract on a
  cleaned 300 dpi page is fast, deterministic and costs no GPU memory. The
  vision model competes with the main model for unified memory, so it is
  escalation, not default.

  Escalate when: mean OCR word confidence < 70, or fewer than 20 characters
  came off a page that is not blank, or the file is a drawing rather than
  a text page.

  A P and ID is not an OCR problem. Prompt the vision model for structure --
  equipment, legible tags, title block, revision block -- as JSON, not prose,
  so each field can be checked. Be honest about the limit: an 8B open-weight
  VLM reads tags and title blocks reliably and does not trace every line on
  a dense drawing.

Every extracted span records source file, page, method and confidence.
That chain is what makes a finding defensible in an audit.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from guard import audit
from tools.base import REGISTRY, prop

OCR_CONFIDENCE_FLOOR = 70
MIN_CHARS_PER_PAGE = 20


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


@REGISTRY.register(
    "ingest_document",
    "Extract text from an uploaded PDF or image, with page-level "
    "provenance. Runs OCR on device and escalates to the vision model "
    "only when confidence is low.",
    {"path": prop("Path to the uploaded file")},
    ["path"],
)
def ingest_document(args: dict) -> str:
    from tools.fs import PathRefused, safe_path

    try:
        path = safe_path(args["path"])
    except PathRefused as exc:
        return f"REFUSED: {exc}"
    if not path.is_file():
        return f"No such file: {args['path']}"

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _ingest_pdf(path)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        return _ingest_image(path)
    if suffix in {".txt", ".md", ".csv"}:
        return path.read_text(encoding="utf-8", errors="replace")[:20000]
    return f"Unsupported file type '{suffix}'."


def _ingest_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError:
        return (
            "pdfplumber is not installed. Run: pip install pdfplumber\n"
            "Until then, attach the document as text."
        )

    pages: list[str] = []
    empty_pages: list[int] = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if len(text) < MIN_CHARS_PER_PAGE:
                empty_pages.append(number)
            pages.append(f"--- page {number} ({path.name}) ---\n{text}")

    audit.write(
        "ingest_pdf",
        {"path": str(path), "pages": len(pages), "needs_ocr": empty_pages},
    )

    body = "\n\n".join(pages)
    if empty_pages:
        body += (
            f"\n\n[Pages {empty_pages} produced almost no text: they are "
            "probably scans. OCR escalation is TODO -- rasterise at 300 dpi, "
            "deskew, denoise, then tesseract, then the vision model if mean "
            "word confidence is under 70.]"
        )
    return body[:20000]


def _ingest_image(path: Path) -> str:
    if not tesseract_available():
        return (
            "Tesseract is not installed on this machine. Install it with:\n"
            "  brew install tesseract   (macOS)\n"
            "  apt install tesseract-ocr  (Debian/Ubuntu)\n"
            "Then retry. No cloud OCR is used or available."
        )
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return "pytesseract and Pillow are not installed. See requirements.txt."

    text = pytesseract.image_to_string(Image.open(path))
    audit.write("ingest_image", {"path": str(path), "chars": len(text)})
    if len(text.strip()) < MIN_CHARS_PER_PAGE:
        return (
            f"OCR produced almost nothing from {path.name}. Escalate with "
            "describe_image, which uses the local vision model."
        )
    return f"--- OCR of {path.name} ---\n{text}"[:20000]


@REGISTRY.register(
    "describe_image",
    "Ask the local vision model what an image or engineering drawing "
    "shows. Use for drawings, photographs and handwriting, where OCR "
    "alone is not enough.",
    {
        "path": prop("Path to the image"),
        "question": prop("What to look for, e.g. equipment tags and title block"),
    },
    ["path"],
)
def describe_image(args: dict) -> str:
    # TODO(phase 2): base64 the image and send it to the vision model over
    # /v1/chat/completions with an image_url content part. The router
    # already selects a visual_understanding model; wire it through here.
    return (
        "Vision model call is not wired up yet (phase 2). The router "
        "selects the visual_understanding model correctly; this tool needs "
        "the image content part added to the chat call."
    )
