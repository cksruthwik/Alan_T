"""Request/response shapes for the HTTP API (API_SPECIFICATION.md)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequestBody(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponseBody(BaseModel):
    session_id: str
    response: str
    model: str | None = None
    status: str = "ok"
    degraded: list[str] = Field(default_factory=list)
