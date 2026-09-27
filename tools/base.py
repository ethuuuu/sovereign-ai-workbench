"""The tool contract.

Fifteen tools, not seventy. The Nova prototype registered around seventy,
which is well past the point where a 27B-class open-weight model picks
reliably, and it cost several thousand tokens of schema on every single
request. Every tool here is safe to hand to a model unattended.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

ToolFn = Callable[[dict[str, Any]], str]


@dataclass
class Tool:
    name: str
    description: str
    fn: ToolFn
    properties: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    capabilities: set[str] = field(default_factory=set)

    def schema(self) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "type": "object",
            "properties": self.properties,
        }
        if self.required:
            parameters["required"] = self.required
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        properties: dict[str, Any] | None = None,
        required: list[str] | None = None,
        capabilities: set[str] | None = None,
    ) -> Callable[[ToolFn], ToolFn]:
        def decorator(fn: ToolFn) -> ToolFn:
            self._tools[name] = Tool(
                name=name,
                description=description,
                fn=fn,
                properties=properties or {},
                required=required or [],
                capabilities=capabilities or set(),
            )
            return fn

        return decorator

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self, only: set[str] | None = None) -> list[dict[str, Any]]:
        """Offer the model a subset when the task does not need everything."""
        tools = self._tools.values()
        if only is not None:
            tools = [t for t in tools if t.name in only]
        return [t.schema() for t in tools]


REGISTRY = ToolRegistry()


def prop(description: str, kind: str = "string") -> dict[str, Any]:
    spec: dict[str, Any] = {"type": kind, "description": description}
    if kind == "array":
        # Some /v1 servers reject an array property with no items schema.
        spec["items"] = {"type": "string"}
    return spec


def load_all() -> ToolRegistry:
    """Import every tool module so its decorators run."""
    from tools import deliver, fs, kb, sandbox, vision  # noqa: F401

    return REGISTRY
