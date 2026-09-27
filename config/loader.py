"""Read the three YAML files once and hand out plain dicts.

Every site-specific value in the workbench lives in config/*.yaml. Nothing
else in the codebase is allowed to hard-code an endpoint, a model name, a
path or a limit.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


def _load(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Missing config file {path}. Copy it from the repo defaults."
        )
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level.")
    return data


@functools.lru_cache(maxsize=None)
def settings() -> dict[str, Any]:
    return _load("settings.yaml")


@functools.lru_cache(maxsize=None)
def policy() -> dict[str, Any]:
    return _load("policy.yaml")


@functools.lru_cache(maxsize=None)
def model_registry() -> dict[str, Any]:
    return _load("models.yaml")


def reload() -> None:
    """Drop the cache. Used by tests and by the /api/reload endpoint."""
    settings.cache_clear()
    policy.cache_clear()
    model_registry.cache_clear()


def resolve_path(key: str) -> Path:
    """Resolve one of settings.paths.* against the repo root."""
    raw = settings().get("paths", {}).get(key)
    if raw is None:
        raise KeyError(f"settings.yaml has no paths.{key}")
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()
