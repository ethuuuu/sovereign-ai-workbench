"""Proof point 1: two task types, two different models, no user input."""

from __future__ import annotations

from router import classify, select
from router.registry import load


def test_registry_loads_and_validates() -> None:
    registry = load()
    assert registry.entries
    assert registry.default() is not None


def test_coding_and_drafting_route_to_different_models() -> None:
    registry = load()

    coding = classify.classify("Write a Python function to size a pipe and test it")
    drafting = classify.classify("Draft an approval note for the inspection findings")

    assert coding.task_type == "code_generation"
    assert drafting.task_type == "document_drafting"

    code_route = select.select(registry, coding.task_type, require_available=False)
    draft_route = select.select(registry, drafting.task_type, require_available=False)

    assert code_route.model.id != draft_route.model.id
    assert code_route.reason and draft_route.reason


def test_image_attachment_forces_visual_understanding() -> None:
    result = classify.classify("What does this show?", ["p_and_id_rev3.png"])
    assert result.task_type == "visual_understanding"
