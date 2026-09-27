"""Fallback tool-call parsing.

Not every open-weight model behind every /v1 server emits native tool
calls. When the server returns plain text, look for a fenced JSON block of
the shape {"tool": "...", "arguments": {...}} and treat it as a call.

Carried over from the Nova prototype, where it was the difference between
a model fleet that worked and one that worked on Tuesdays.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCED = re.compile(r"```(?:json|tool)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE = re.compile(r'(\{\s*"tool"\s*:.*?\})', re.DOTALL)


def instructions(tool_schemas: list[dict[str, Any]]) -> str:
    """Appended to the system prompt when native tool calling is off."""
    names = [t["function"]["name"] for t in tool_schemas]
    return (
        "\n\nTOOL PROTOCOL\n"
        "To use a tool, reply with nothing but a fenced JSON block:\n"
        '```json\n{"tool": "<name>", "arguments": {...}}\n```\n'
        f"Available tools: {', '.join(names)}.\n"
        "One tool per reply. When the task is done, reply in plain prose "
        "with no JSON block."
    )


def parse(text: str) -> list[dict[str, Any]]:
    """Return tool calls in the same shape the OpenAI SDK produces."""
    if not text:
        return []

    candidates = _FENCED.findall(text) or _BARE.findall(text)
    calls: list[dict[str, Any]] = []
    for index, blob in enumerate(candidates):
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        name = parsed.get("tool") or parsed.get("name")
        if not name:
            continue
        arguments = parsed.get("arguments") or parsed.get("args") or {}
        calls.append(
            {
                "id": f"fallback_{index}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
            }
        )
    return calls


def strip_calls(text: str) -> str:
    """The prose left over once tool blocks are removed."""
    return _FENCED.sub("", _BARE.sub("", text or "")).strip()
