"""Pick a model for a task, and say why in one sentence.

The reason string is not decoration. It is printed in the UI and written
to the audit log, so a routing decision can be challenged and checked.
"""

from __future__ import annotations

from dataclasses import dataclass

from guard import audit
from router.registry import ModelEntry, Registry

TASK_CAPABILITY = {
    "code_generation": "code_generation",
    "code_repair": "code_repair",
    "document_drafting": "document_drafting",
    "summarisation": "summarisation",
    "retrieval_qa": "retrieval_qa",
    "calculation": "calculation",
    "visual_understanding": "visual_understanding",
    "classification": "classification",
    "general": "general",
}


@dataclass
class Route:
    model: ModelEntry
    task_type: str
    reason: str

    def as_event(self) -> dict:
        return {
            "model": self.model.id,
            "endpoint_model": self.model.endpoint_model,
            "task_type": self.task_type,
            "reason": self.reason,
        }


def select(
    registry: Registry,
    task_type: str,
    estimated_prompt_tokens: int = 0,
    require_available: bool = True,
) -> Route:
    capability = TASK_CAPABILITY.get(task_type, "general")
    candidates = registry.with_capability(capability)

    if require_available:
        live = [c for c in candidates if c.available]
        if live:
            candidates = live
        elif candidates:
            names = ", ".join(c.id for c in candidates)
            fallback = registry.default()
            route = Route(
                fallback,
                task_type,
                f"{task_type}: {names} declare it but are not loaded on the "
                f"endpoint; fell back to default {fallback.id}",
            )
            audit.write("route", route.as_event())
            return route

    headroom = [c for c in candidates if c.context_window >= estimated_prompt_tokens]
    if headroom:
        candidates = headroom
    elif candidates:
        widest = max(candidates, key=lambda c: c.context_window)
        route = Route(
            widest,
            task_type,
            f"{task_type}: prompt is ~{estimated_prompt_tokens} tokens, wider "
            f"than any candidate; chose {widest.id}, the widest at "
            f"{widest.context_window}",
        )
        audit.write("route", route.as_event())
        return route

    if not candidates:
        fallback = registry.default()
        route = Route(
            fallback,
            task_type,
            f"{task_type}: no model declares '{capability}'; fell back to "
            f"default {fallback.id}",
        )
        audit.write("route", route.as_event())
        return route

    chosen = sorted(candidates, key=lambda c: (c.speed_rank, -c.context_window))[0]

    if len(candidates) == 1:
        why = f"only model declaring '{capability}'"
    else:
        others = ", ".join(c.id for c in candidates if c.id != chosen.id)
        why = f"fastest of {len(candidates)} declaring '{capability}' (over {others})"

    route = Route(
        chosen,
        task_type,
        f"{task_type} + ~{estimated_prompt_tokens} tokens -> {chosen.id} ({why})",
    )
    audit.write("route", route.as_event())
    return route
