"""Turn a request into a task type.

Two tiers, so the common case costs nothing:
  1. Rules -- attachments and verb patterns settle most requests for free.
  2. A small model constrained to the fixed label list, when no rule fires.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

TASK_TYPES = (
    "code_generation",
    "document_drafting",
    "retrieval_qa",
    "calculation",
    "visual_understanding",
    "summarisation",
    "general",
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
SCAN_SUFFIXES = IMAGE_SUFFIXES | {".pdf"}

_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "code_generation",
        re.compile(
            r"\b(write|fix|debug|refactor|implement|run|execute|test)\b.{0,40}"
            r"\b(code|script|function|program|python|sql|module|test)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "document_drafting",
        re.compile(
            r"\b(draft|write|prepare|generate|create)\b.{0,40}"
            r"\b(note|memo|letter|report|minutes|approval|deck|presentation|"
            r"proposal|spreadsheet)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "calculation",
        re.compile(
            r"\b(calculate|compute|sizing|thickness|flow ?rate|tonnage|"
            r"derate|estimate)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "retrieval_qa",
        re.compile(
            r"\b(according to|as per|what does the|clause|sop|manual|standard|"
            r"procedure|policy)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "summarisation",
        re.compile(r"\b(summari[sz]e|tl;?dr|key points|brief me)\b", re.IGNORECASE),
    ),
]


@dataclass
class Classification:
    task_type: str
    reason: str
    used_model: bool = False


def classify(
    request: str,
    attachments: list[str] | None = None,
    classifier_model: str | None = None,
) -> Classification:
    attachments = attachments or []

    for name in attachments:
        suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if suffix in SCAN_SUFFIXES:
            return Classification(
                "visual_understanding",
                f"attachment '{name}' is an image or PDF",
            )

    for task_type, pattern in _RULES:
        match = pattern.search(request)
        if match:
            return Classification(
                task_type, f"matched rule on '{match.group(0).strip()}'"
            )

    if classifier_model:
        guessed = _ask_model(request, classifier_model)
        if guessed:
            return Classification(guessed, "classified by small model", True)

    return Classification("general", "no rule matched; defaulted to general")


def _ask_model(request: str, model: str) -> str | None:
    from inference.client import chat

    prompt = (
        "Classify this request into exactly one label.\n"
        f"Labels: {', '.join(TASK_TYPES)}\n"
        'Reply with only JSON: {"label": "<one label>"}\n\n'
        f"Request: {request[:1200]}"
    )
    try:
        result = chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=32,
            temperature=0.0,
        )
        content = result["message"].get("content") or ""
        match = re.search(r'\{[^{}]*"label"[^{}]*\}', content, re.DOTALL)
        if not match:
            return None
        label = json.loads(match.group(0)).get("label")
        return label if label in TASK_TYPES else None
    except Exception:  # noqa: BLE001 - classification is best effort
        return None
