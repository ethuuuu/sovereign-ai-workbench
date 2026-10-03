"""Write one deliverable, then exit.

This is the only process in the system allowed to import python-docx,
python-pptx or openpyxl. All three reach lxml, which requires the GIL, and
enabling the GIL is a ONE-WAY LATCH: there is no API to turn it off again,
and unloading the module does not help.

    >>> sys._is_gil_enabled()        # free-threaded start
    False
    >>> import lxml.etree
    >>> sys._is_gil_enabled()
    True
    >>> del sys.modules['lxml.etree']; gc.collect()
    >>> sys._is_gil_enabled()
    True                             # still on, for the life of the process

So the GIL is confined to a process that lives for about 160 ms. The agent
keeps running GIL-free, and the latch dies with this worker.

Protocol: one JSON job on stdin, one JSON result on stdout. No imports at
module level -- each handler imports only what it needs, so a .xlsx job
never loads lxml at all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLACEHOLDERS = ("TODO", "[insert", "lorem ipsum", "XXXX")


def write_docx(job: dict) -> dict:
    from docx import Document

    content = job["content"]
    path = Path(job["path"])
    document = Document()
    document.add_heading(job.get("title", ""), level=0)

    for label in ("reference", "date", "subject"):
        value = content.get(label)
        if value:
            document.add_paragraph(f"{label.title()}: {value}")

    if content.get("background"):
        document.add_heading("Background", level=1)
        document.add_paragraph(str(content["background"]))

    observations = content.get("observations") or []
    if observations:
        document.add_heading("Observations", level=1)
        table = document.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        head = table.rows[0].cells
        head[0].text, head[1].text, head[2].text = "Finding", "Severity", "Source"
        for item in observations:
            row = table.add_row().cells
            row[0].text = str(item.get("finding", ""))
            row[1].text = str(item.get("severity", ""))
            row[2].text = str(item.get("source", ""))

    if content.get("recommendation"):
        document.add_heading("Recommendation", level=1)
        document.add_paragraph(str(content["recommendation"]))

    document.add_paragraph("")
    document.add_paragraph(f"Prepared by: {content.get('prepared_by', '')}")
    document.add_paragraph("Approved by: ______________________")
    document.save(path)

    # Verify in the same process: re-open what we just wrote.
    reopened = Document(path)
    text = "\n".join(p.text for p in reopened.paragraphs)
    for placeholder in PLACEHOLDERS:
        if placeholder.lower() in text.lower():
            # Do not leave a rejected draft on disk for someone to send.
            path.unlink(missing_ok=True)
            return {"ok": False, "error": f"placeholder '{placeholder}' survived"}
    return {"ok": True, "path": str(path), "bytes": path.stat().st_size}


def write_xlsx(job: dict) -> dict:
    from openpyxl import Workbook, load_workbook

    path = Path(job["path"])
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet in job["content"].get("sheets", []):
        worksheet = workbook.create_sheet(title=str(sheet.get("name", "Sheet"))[:31])
        for row in sheet.get("rows", []):
            worksheet.append(row)
    if not workbook.sheetnames:
        return {"ok": False, "error": "no sheets in sheet_json"}
    workbook.save(path)

    load_workbook(path)  # re-open check
    return {"ok": True, "path": str(path), "bytes": path.stat().st_size}


def write_pptx(job: dict) -> dict:
    from pptx import Presentation

    path = Path(job["path"])
    presentation = Presentation()
    layout = presentation.slide_layouts[1]
    for spec in job["content"].get("slides", []):
        slide = presentation.slides.add_slide(layout)
        slide.shapes.title.text = str(spec.get("title", ""))
        frame = slide.placeholders[1].text_frame
        for index, bullet in enumerate(spec.get("bullets") or []):
            para = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            para.text = str(bullet)
    presentation.save(path)

    Presentation(path)  # re-open check
    return {"ok": True, "path": str(path), "bytes": path.stat().st_size}


HANDLERS = {"docx": write_docx, "xlsx": write_xlsx, "pptx": write_pptx}


def main() -> int:
    try:
        job = json.loads(sys.stdin.read())
        handler = HANDLERS.get(job.get("kind", ""))
        if handler is None:
            result = {"ok": False, "error": f"unknown kind '{job.get('kind')}'"}
        else:
            result = handler(job)
            result["gil_enabled_in_worker"] = sys._is_gil_enabled() if hasattr(
                sys, "_is_gil_enabled"
            ) else True
    except Exception as exc:  # noqa: BLE001 - reported, never raised at the agent
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
