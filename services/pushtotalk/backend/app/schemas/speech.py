"""Контракт HTTP API.

Схемы описывают ровно то, что отправляет и ожидает Android-клиент
(`data/network/dto` в приложении).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.timeutils import as_almaty


class SpeechRequest(BaseModel):
    """Тело POST /api/speech."""

    text: str = Field(..., description="Распознанный текст реплики")


class SpeechResponse(BaseModel):
    """Успешный ответ POST /api/speech."""

    status: str = "ok"
    id: int


class TranscriptionResponse(BaseModel):
    """Успешный ответ POST /api/speech/transcribe."""

    status: str = "ok"
    text: str


class ErrorResponse(BaseModel):
    """Ответ на любую обработанную ошибку."""

    status: str = "error"
    message: str


class MessageResponse(BaseModel):
    """Элемент истории GET /api/messages."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    created_at: datetime
    status: str

    @field_validator("created_at")
    @classmethod
    def _mark_timezone(cls, value: datetime) -> datetime:
        """В базе время наивное; в ответ добавляем `+05:00`.

        Иначе клиент вправе прочитать метку как UTC и показать её на пять
        часов раньше.
        """
        return as_almaty(value)


class HealthResponse(BaseModel):
    """Ответ GET /api/health."""

    status: str = "ok"
    version: str
