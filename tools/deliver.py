"""Deliverable generation: the output is a file, not a chat reply.

The model does not produce formatting. It produces structured content
matching a schema, and a renderer merges that into a template carrying the
organisation's letterhead, fonts and numbering. Three reasons:

  - approval notes follow a house format, and getting the format right
    matters as much as the content
  - a template is something the customer edits in Word, without code
  - schema-constrained JSON is far more reliable from a 27B open-weight
    model than well-formatted long prose, and it is checkable before
    rendering

NOTHING IN THIS MODULE IMPORTS python-docx, python-pptx OR openpyxl.
All three reach lxml, which requires the GIL, and enabling the GIL cannot
be undone for the life of a process. The actual writing happens in
scripts/deliver_worker.py, dispatched through tools/isolated.py, so the
agent keeps free threading. See README, 'Free-threaded Python'.

Every generated file is re-opened and verified inside that worker before
it is reported: it parses, required sections exist, no placeholder
survives. A corrupt download in front of a jury is an avoidable failure.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from config import resolve_path
from guard import audit
from tools.base import REGISTRY, prop
from tools.isolated import run_job

APPROVAL_NOTE_SCHEMA = {
    "reference": "string, e.g. INS/2026/014",
    "date": "YYYY-MM-DD",
    "subject": "one line",
    "background": "2-4 sentences of context",
    "observations": [
        {
            "finding": "what was observed",
            "severity": "High | Medium | Low",
            "source": "file and page the finding came from",
        }
    ],
    "recommendation": "what approval is sought, and why",
    "prepared_by": "name and designation",
}


def _output_dir() -> Path:
    path = resolve_path("workspace") / "deliverables"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dispatch(kind: str, filename: str, title: str, raw_json: str, field: str) -> str:
    try:
        content = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return f"{field} is not valid JSON ({exc}). Fix it and retry."

    path = _output_dir() / Path(filename).name
    result = run_job(kind, path, title, content)

    if not result.get("ok"):
        return f"Could not write {path.name}: {result.get('error', 'unknown error')}"

    audit.write("deliverable", {"kind": kind, "path": str(path)})
    where = "in an isolated worker" if result.get("isolated") else "in process"
    return (
        f"Wrote and verified {path.name} ({result.get('bytes', 0)} bytes) "
        f"in {path.parent} [{where}]"
    )


@REGISTRY.register(
    "make_docx",
    "Write a Word document from structured content. For an approval note "
    f"use this shape: {json.dumps(APPROVAL_NOTE_SCHEMA)}",
    {
        "filename": prop("Output file name, ending in .docx"),
        "title": prop("Document title"),
        "content_json": prop("The structured content, as a JSON string"),
    },
    ["filename", "title", "content_json"],
)
def make_docx(args: dict) -> str:
    content = dict(json.loads(args["content_json"])) if _is_json(
        args["content_json"]
    ) else None
    if content is not None:
        content.setdefault("date", date.today().isoformat())
        return _dispatch(
            "docx", args["filename"], args["title"], json.dumps(content),
            "content_json",
        )
    return _dispatch(
        "docx", args["filename"], args["title"], args["content_json"], "content_json"
    )


@REGISTRY.register(
    "make_xlsx",
    "Write a spreadsheet. For a calculation, put inputs in cells and "
    "intermediate steps in real formulas referencing them, so a reviewer "
    "can change an input and watch the answer move. Never type in a "
    "number the formula should compute.",
    {
        "filename": prop("Output file name, ending in .xlsx"),
        "sheet_json": prop(
            'JSON: {"sheets": [{"name": "Calc", "rows": [["Label", "=B1*2"]]}]}'
        ),
    },
    ["filename", "sheet_json"],
)
def make_xlsx(args: dict) -> str:
    return _dispatch("xlsx", args["filename"], "", args["sheet_json"], "sheet_json")


@REGISTRY.register(
    "make_pptx",
    "Write a PowerPoint deck from a list of slides.",
    {
        "filename": prop("Output file name, ending in .pptx"),
        "slides_json": prop('JSON: {"slides": [{"title": "...", "bullets": [...]}]}'),
    },
    ["filename", "slides_json"],
)
def make_pptx(args: dict) -> str:
    return _dispatch("pptx", args["filename"], "", args["slides_json"], "slides_json")


@REGISTRY.register(
    "finish",
    "Call this when the task is complete. Summarise what was done and "
    "list any files produced.",
    {
        "summary": prop("What was accomplished, in two or three sentences"),
        "files": prop("File names produced", "array"),
    },
    ["summary"],
)
def finish(args: dict) -> str:
    audit.write("finish", {"summary": args.get("summary", "")})
    return "FINISHED"


def _is_json(text: str) -> bool:
    try:
        return isinstance(json.loads(text), dict)
    except json.JSONDecodeError:
        return False
