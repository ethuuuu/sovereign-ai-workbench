"""Load and validate models.yaml, and index it by capability."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import model_registry

SPEED_ORDER = {"fast": 0, "medium": 1, "slow": 2}

KNOWN_CAPABILITIES = {
    "code_generation",
    "code_repair",
    "structured_output",
    "document_drafting",
    "summarisation",
    "retrieval_qa",
    "calculation",
    "visual_understanding",
    "ocr_assist",
    "classification",
    "general",
}


@dataclass
class ModelEntry:
    id: str
    endpoint_model: str
    capabilities: set[str]
    context_window: int
    speed_class: str = "medium"
    default: bool = False
    notes: str = ""
    available: bool = True

    @property
    def speed_rank(self) -> int:
        return SPEED_ORDER.get(self.speed_class, 1)


@dataclass
class Registry:
    entries: list[ModelEntry] = field(default_factory=list)

    def by_id(self, model_id: str) -> ModelEntry | None:
        return next((e for e in self.entries if e.id == model_id), None)

    def default(self) -> ModelEntry:
        explicit = next((e for e in self.entries if e.default), None)
        if explicit:
            return explicit
        if not self.entries:
            raise RuntimeError("models.yaml declares no models.")
        return self.entries[0]

    def with_capability(self, capability: str) -> list[ModelEntry]:
        return [e for e in self.entries if capability in e.capabilities]

    def raw(self) -> list[dict[str, Any]]:
        return [{"id": e.id, "endpoint_model": e.endpoint_model} for e in self.entries]

    def mark_availability(self, available_ids: list[str]) -> None:
        known = set(available_ids)
        for entry in self.entries:
            entry.available = entry.id in known


def load() -> Registry:
    raw = model_registry().get("models") or []
    if not raw:
        raise RuntimeError("models.yaml has no 'models:' list.")

    entries: list[ModelEntry] = []
    seen: set[str] = set()
    defaults = 0

    for item in raw:
        for required in ("id", "endpoint_model", "capabilities", "context_window"):
            if required not in item:
                raise ValueError(f"models.yaml entry missing '{required}': {item}")

        model_id = str(item["id"])
        if model_id in seen:
            raise ValueError(f"models.yaml has two entries with id '{model_id}'")
        seen.add(model_id)

        capabilities = set(item["capabilities"])
        unknown = capabilities - KNOWN_CAPABILITIES
        if unknown:
            raise ValueError(
                f"models.yaml entry '{model_id}' declares unknown capabilities "
                f"{sorted(unknown)}. Known: {sorted(KNOWN_CAPABILITIES)}"
            )

        is_default = bool(item.get("default", False))
        defaults += int(is_default)

        entries.append(
            ModelEntry(
                id=model_id,
                endpoint_model=str(item["endpoint_model"]),
                capabilities=capabilities,
                context_window=int(item["context_window"]),
                speed_class=str(item.get("speed_class", "medium")),
                default=is_default,
                notes=str(item.get("notes", "")),
            )
        )

    if defaults > 1:
        raise ValueError("models.yaml marks more than one model as default.")
    return Registry(entries)
