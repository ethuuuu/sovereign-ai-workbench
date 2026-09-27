"""The only module in the workbench that opens a network connection.

It speaks the OpenAI-compatible /v1 protocol and nothing else. That is what
makes the backend swappable: vLLM on a CUDA server, MLX on Apple silicon,
llama.cpp or Ollama on a workstation. Point settings.yaml somewhere else
and no other file changes.

The base URL is checked against the egress policy at import time, so a
misconfigured settings.yaml fails loudly at startup rather than quietly
sending a P and ID to someone else's server.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

from openai import OpenAI

from config import policy, settings
from guard import audit

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class InferenceUnavailable(RuntimeError):
    """The /v1 endpoint could not be reached or refused the request."""


def _check_base_url(base_url: str) -> None:
    host = urlparse(base_url).hostname or ""
    permitted = set(policy().get("egress", {}).get("allowed_hosts", [])) | _LOOPBACK
    if host not in permitted:
        raise RuntimeError(
            f"settings.yaml points inference at '{host}', which policy.yaml does "
            f"not allow. Permitted: {sorted(permitted)}. Refusing to start."
        )


_client: OpenAI | None = None
_embed_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        conf = settings()["inference"]
        _check_base_url(conf["base_url"])
        _client = OpenAI(
            base_url=conf["base_url"],
            api_key=conf.get("api_key", "local"),
            timeout=float(conf.get("timeout_seconds", 180)),
            max_retries=1,
        )
    return _client


def embed_client() -> OpenAI:
    global _embed_client
    if _embed_client is None:
        conf = settings().get("embeddings") or settings()["inference"]
        _check_base_url(conf["base_url"])
        _embed_client = OpenAI(
            base_url=conf["base_url"],
            api_key=conf.get("api_key", "local"),
            timeout=float(conf.get("timeout_seconds", 180)),
            max_retries=1,
        )
    return _embed_client


def list_models() -> list[str]:
    """Model ids the server currently has loaded."""
    try:
        return [m.id for m in client().models.list().data]
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        raise InferenceUnavailable(
            f"Could not reach {settings()['inference']['base_url']}: {exc}"
        ) from exc


def chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One chat completion. Returns the raw message dict plus usage.

    Servers differ in what they accept, so unsupported extras are dropped
    on a retry rather than crashing the run.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if response_format:
        kwargs["response_format"] = response_format

    started = time.monotonic()
    try:
        response = client().chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        if tools and _looks_like_tools_unsupported(exc):
            audit.write("model_tools_unsupported", {"model": model})
            kwargs.pop("tools", None)
            kwargs.pop("tool_choice", None)
            response = client().chat.completions.create(**kwargs)
        else:
            raise InferenceUnavailable(str(exc)) from exc

    elapsed_ms = int((time.monotonic() - started) * 1000)
    choice = response.choices[0]
    usage = getattr(response, "usage", None)

    audit.write(
        "model_call",
        {
            "model": model,
            "elapsed_ms": elapsed_ms,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "finish_reason": choice.finish_reason,
            "tools_offered": len(tools or []),
        },
    )

    return {
        "message": choice.message.model_dump(exclude_unset=False),
        "finish_reason": choice.finish_reason,
        "elapsed_ms": elapsed_ms,
        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
    }


def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    conf = settings().get("embeddings", {})
    name = model or conf.get("model", "bge-m3")
    response = embed_client().embeddings.create(model=name, input=texts)
    return [item.embedding for item in response.data]


def _looks_like_tools_unsupported(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in ("tool", "function call", "not supported", "unrecognized")
    )
