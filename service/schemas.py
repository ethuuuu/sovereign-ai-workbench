"""Request and response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    session_id: str | None = None
    attachments: list[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    session_id: str
    workspace: str
    created: str


class ModelInfo(BaseModel):
    id: str
    endpoint_model: str
    capabilities: list[str]
    context_window: int
    speed_class: str
    default: bool
    available: bool


class ModelsResponse(BaseModel):
    endpoint: str
    reachable: bool
    error: str | None = None
    models: list[ModelInfo]


class EgressResponse(BaseModel):
    installed: bool
    external_calls: int
    loopback_calls: int
    allowed_hosts: list[str]
    violations: list[dict]


class KbSearchRequest(BaseModel):
    query: str
    top_k: int = 5
