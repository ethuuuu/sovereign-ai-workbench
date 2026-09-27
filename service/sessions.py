"""One workspace directory per session. No database.

A Postgres dependency buys nothing here and adds a service that has to be
installed and secured at every site.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import resolve_path


@dataclass
class Session:
    id: str
    root: Path
    created: str
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def uploads(self) -> Path:
        path = self.root / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def deliverables(self) -> Path:
        path = self.root / "deliverables"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def snapshot(self) -> None:
        (self.root / "history.json").write_text(
            json.dumps(self.history, indent=2, default=str), encoding="utf-8"
        )


_sessions: dict[str, Session] = {}


def create() -> Session:
    session_id = uuid.uuid4().hex[:12]
    root = resolve_path("workspace") / session_id
    root.mkdir(parents=True, exist_ok=True)
    session = Session(
        id=session_id,
        root=root,
        created=datetime.now(timezone.utc).isoformat(),
    )
    _sessions[session_id] = session
    return session


def get(session_id: str) -> Session | None:
    session = _sessions.get(session_id)
    if session:
        return session
    root = resolve_path("workspace") / session_id
    if root.is_dir():
        session = Session(session_id, root, datetime.now(timezone.utc).isoformat())
        _sessions[session_id] = session
        return session
    return None


def get_or_create(session_id: str | None) -> Session:
    if session_id:
        existing = get(session_id)
        if existing:
            return existing
    return create()


def deliverables(session: Session) -> list[dict[str, Any]]:
    out = []
    for path in sorted(session.deliverables.glob("*")):
        if path.is_file():
            out.append({"name": path.name, "bytes": path.stat().st_size})
    return out


def purge(session_id: str) -> bool:
    session = _sessions.pop(session_id, None)
    root = (session.root if session else resolve_path("workspace") / session_id)
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
        return True
    return False
