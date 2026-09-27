"""Append-only audit log.

One JSON object per line. Every model call, tool call, file write and
blocked egress attempt lands here. This is the artefact a compliance
officer asks for, and it is what the demo scrolls through at the end.

Never rewrites or truncates an existing file.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import policy, resolve_path

_lock = threading.Lock()
_session_id: str = "boot"


def set_session(session_id: str) -> None:
    global _session_id
    _session_id = session_id


def _log_path() -> Path:
    directory = resolve_path("audit")
    directory.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return directory / f"audit-{day}.jsonl"


def write(event: str, payload: dict[str, Any] | None = None) -> None:
    if not policy().get("audit", {}).get("enabled", True):
        return
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "session": _session_id,
        "pid": os.getpid(),
        "event": event,
        "data": payload or {},
    }
    line = json.dumps(record, default=str, ensure_ascii=False)
    with _lock:
        with _log_path().open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def read_session(session_id: str, limit: int = 500) -> list[dict[str, Any]]:
    """Every recorded event for one session, oldest first."""
    directory = resolve_path("audit")
    if not directory.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("audit-*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("session") == session_id:
                    out.append(record)
    return out[-limit:]
