"""Ask the model for a plan before it touches anything.

Two reasons this is not ceremony. A user in a refinery wants to see what
the assistant intends to do before it writes files. And a visible plan
makes a stalled run diagnosable instead of mysterious.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from inference.client import chat

_JSON_BLOCK = re.compile(r"\[.*\]", re.DOTALL)


@dataclass
class Step:
    n: int
    action: str
    tool: str
    why: str


PLAN_PROMPT = """Break this request into at most 6 concrete steps.

Available tools: {tools}

Reply with ONLY a JSON array, no prose:
[{{"n": 1, "action": "what you will do", "tool": "tool_name or none",
   "why": "why this step is needed"}}]

Request: {request}"""


def plan(request: str, model: str, tool_names: list[str]) -> list[Step]:
    """Best effort. A failed plan is not fatal -- the loop still runs."""
    try:
        result = chat(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": PLAN_PROMPT.format(
                        tools=", ".join(tool_names), request=request[:2000]
                    ),
                }
            ],
            max_tokens=700,
            temperature=0.2,
        )
        content = result["message"].get("content") or ""
        match = _JSON_BLOCK.search(content)
        if not match:
            return []
        raw = json.loads(match.group(0))
    except Exception:  # noqa: BLE001 - planning is advisory
        return []

    steps: list[Step] = []
    for index, item in enumerate(raw[:6], start=1):
        if not isinstance(item, dict):
            continue
        steps.append(
            Step(
                n=int(item.get("n", index)),
                action=str(item.get("action", "")),
                tool=str(item.get("tool", "none")),
                why=str(item.get("why", "")),
            )
        )
    return steps
