"""Reconcile the model registry against what the server actually has.

A model declared in models.yaml but not loaded on the endpoint should
degrade routing gracefully, not throw halfway through a demo.
"""

from __future__ import annotations

from dataclasses import dataclass

from guard import audit
from inference.client import InferenceUnavailable, list_models


@dataclass
class Health:
    endpoint_reachable: bool
    server_models: list[str]
    available_ids: list[str]
    missing_ids: list[str]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.endpoint_reachable and bool(self.available_ids)


def check(registry_entries: list[dict]) -> Health:
    try:
        server_models = list_models()
    except InferenceUnavailable as exc:
        audit.write("discovery_failed", {"error": str(exc)})
        return Health(False, [], [], [e["id"] for e in registry_entries], str(exc))

    loaded = set(server_models)
    available, missing = [], []
    for entry in registry_entries:
        (available if entry["endpoint_model"] in loaded else missing).append(
            entry["id"]
        )

    audit.write(
        "discovery",
        {"server_models": server_models, "available": available, "missing": missing},
    )
    return Health(True, server_models, available, missing)
