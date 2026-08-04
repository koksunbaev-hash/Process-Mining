"""Shared payload models for HTTP and MQTT voice events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class VoiceCommandEvent(BaseModel):
    text: str = Field(min_length=1)
    project: str = "kms"
    source: str = "ovos"
    request_id: str | None = None
    user_id: str | None = None
    device_id: str | None = None
    intent: str | None = None
    confidence: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("text is required")
        return text


class RouteResult(BaseModel):
    status: str
    project: str
    forwarded: bool = False
    reason: str | None = None
    adapter_response: dict[str, Any] | None = None
