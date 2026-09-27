"""Structured run events. The UI renders these live; audit keeps them."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from guard import audit

EventSink = Callable[[dict[str, Any]], None]


@dataclass
class Trace:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    sinks: list[EventSink] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def subscribe(self, sink: EventSink) -> None:
        self.sinks.append(sink)

    def emit(self, kind: str, **data: Any) -> dict[str, Any]:
        event = {
            "run": self.run_id,
            "at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            **data,
        }
        self.events.append(event)
        audit.write(f"trace.{kind}", data)
        for sink in self.sinks:
            try:
                sink(event)
            except Exception:  # noqa: BLE001 - a broken sink must not stop a run
                pass
        return event
