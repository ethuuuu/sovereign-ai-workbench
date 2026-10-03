"""Keep the GIL out of the agent process.

Enabling the GIL is a one-way latch: there is no API to disable it again
(`sys._is_gil_enabled` is read-only, and the C side exports only
PyUnstable_Module_SetGIL, which just enables). So a single call to
make_docx would cost the agent its free threading for the rest of the
session -- every later ingest, every later BM25 query, back under the GIL.

The fix is a process boundary. GIL-requiring work runs in a short-lived
worker that imports lxml, does the job and exits; the latch dies with it.

Measured cost of that worker, writing a real 40-paragraph approval note:

    bare interpreter start        18 ms
    + import python-docx         120 ms
    + write and verify the file  159 ms

About a sixth of a second, once per document, against keeping the GIL off
for the whole session. On a standard (non-free-threaded) interpreter there
is nothing to protect, so this does NOT fork -- it runs in-process and
pays nothing. Isolation only happens when it buys something.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent.parallel import gil_state
from config import REPO_ROOT
from guard import audit

WORKER = REPO_ROOT / "scripts" / "deliver_worker.py"
TIMEOUT_SECONDS = 60

# Writers that reach lxml and therefore require the GIL.
GIL_BOUND_KINDS = {"docx", "xlsx", "pptx"}


def should_isolate() -> bool:
    """Only when there is free threading left to protect."""
    return gil_state().scales


def run_job(kind: str, path: Path, title: str, content: dict[str, Any]) -> dict:
    job = {
        "kind": kind,
        "path": str(path),
        "title": title,
        "content": content,
    }
    if should_isolate():
        return _in_worker(job)
    return _in_process(job)


def _in_worker(job: dict) -> dict:
    try:
        completed = subprocess.run(
            [sys.executable, str(WORKER)],
            input=json.dumps(job),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            cwd=str(REPO_ROOT),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"worker timed out after {TIMEOUT_SECONDS}s"}

    raw = (completed.stdout or "").strip()
    if not raw:
        return {
            "ok": False,
            "error": f"worker produced no result (exit {completed.returncode}): "
                     f"{(completed.stderr or '')[:400]}",
        }
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"worker returned non-JSON: {raw[:300]}"}

    result["isolated"] = True
    audit.write(
        "deliverable_isolated",
        {
            "kind": job["kind"],
            "ok": result.get("ok"),
            "gil_in_worker": result.get("gil_enabled_in_worker"),
            "gil_in_agent": gil_state().gil_currently_enabled,
        },
    )
    return result


def _in_process(job: dict) -> dict:
    """Standard interpreter: no free threading at stake, so no fork."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import deliver_worker

    handler = deliver_worker.HANDLERS.get(job["kind"])
    if handler is None:
        return {"ok": False, "error": f"unknown kind '{job['kind']}'"}
    try:
        result = handler(job)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    result["isolated"] = False
    audit.write("deliverable_inprocess", {"kind": job["kind"], "ok": result.get("ok")})
    return result
