"""Keep the conversation inside the model's context window.

Rewritten from the Nova prototype, where compression fired at 3,500
estimated tokens because a comment confused the server's max output tokens
with the context window. Here the threshold is a fraction of the selected
model's declared window, read from policy.yaml.
"""

from __future__ import annotations

import json
from typing import Any

from config import policy

RECENT_TURNS_PROTECTED = 6


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Roughly four characters per token. Cheap, and close enough to budget."""
    total = 0
    for message in messages:
        total += len(str(message.get("content") or ""))
        calls = message.get("tool_calls")
        if calls:
            total += len(json.dumps(calls, default=str))
    return total // 4


def threshold(context_window: int) -> int:
    fraction = policy().get("agent", {}).get("compress_at_context_fraction", 0.6)
    return int(context_window * float(fraction))


def should_compress(messages: list[dict[str, Any]], context_window: int) -> bool:
    return estimate_tokens(messages) > threshold(context_window)


def compress(
    messages: list[dict[str, Any]],
    context_window: int,
    summarise: Any = None,
) -> list[dict[str, Any]]:
    """Pin the system prompt, protect recent turns, digest the middle."""
    if len(messages) <= RECENT_TURNS_PROTECTED + 1:
        return messages

    system_message = messages[0]
    recent = messages[-RECENT_TURNS_PROTECTED:]
    middle = messages[1:-RECENT_TURNS_PROTECTED]
    if not middle:
        return messages

    digest = _extractive(middle)
    if summarise is not None:
        try:
            digest = summarise(digest) or digest
        except Exception:  # noqa: BLE001 - fall back to the extractive digest
            pass

    return [
        system_message,
        {
            "role": "user",
            "content": f"[Earlier in this run, condensed]\n{digest}",
        },
        {"role": "assistant", "content": "Understood, I have that context."},
        *recent,
    ]


def _extractive(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = message.get("role", "")
        content = str(message.get("content") or "")
        if role == "user" and content and not content.startswith("[Earlier"):
            lines.append(f"- asked: {content[:140]}")
        elif role == "assistant":
            calls = message.get("tool_calls") or []
            if calls:
                names = [
                    (c.get("function", {}) or {}).get("name", "?")
                    if isinstance(c, dict)
                    else "?"
                    for c in calls
                ]
                lines.append(f"- called: {', '.join(names)}")
            elif content:
                lines.append(f"- said: {content[:140]}")
        elif role == "tool" and content:
            lines.append(f"  -> {content[:120]}")
    return "\n".join(lines)
