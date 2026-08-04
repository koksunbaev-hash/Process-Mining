"""РљРѕРЅС‚СЂР°РєС‚ HTTP API.

РЎС…РµРјС‹ РѕРїРёСЃС‹РІР°СЋС‚ СЂРѕРІРЅРѕ С‚Рѕ, С‡С‚Рѕ РѕС‚РїСЂР°РІР»СЏРµС‚ Рё РѕР¶РёРґР°РµС‚ Android-РєР»РёРµРЅС‚
(`data/network/dto` РІ РїСЂРёР»РѕР¶РµРЅРёРё).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.timeutils import as_almaty


class SpeechRequest(BaseModel):
    """РўРµР»Рѕ POST /api/speech."""

    text: str = Field(..., description="Р Р°СЃРїРѕР·РЅР°РЅРЅС‹Р№ С‚РµРєСЃС‚ СЂРµРїР»РёРєРё")


class SpeechResponse(BaseModel):
    """РЈСЃРїРµС€РЅС‹Р№ РѕС‚РІРµС‚ POST /api/speech."""

    status: str = "ok"
    id: int


class TranscriptionResponse(BaseModel):
    """РЈСЃРїРµС€РЅС‹Р№ РѕС‚РІРµС‚ POST /api/speech/transcribe."""

    status: str = "ok"
    text: str


class ErrorResponse(BaseModel):
    """РћС‚РІРµС‚ РЅР° Р»СЋР±СѓСЋ РѕР±СЂР°Р±РѕС‚Р°РЅРЅСѓСЋ РѕС€РёР±РєСѓ."""

    status: str = "error"
    message: str


class MessageResponse(BaseModel):
    """Р­Р»РµРјРµРЅС‚ РёСЃС‚РѕСЂРёРё GET /api/messages."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    created_at: datetime
    status: str

    @field_validator("created_at")
    @classmethod
    def _mark_timezone(cls, value: datetime) -> datetime:
        """Р’ Р±Р°Р·Рµ РІСЂРµРјСЏ РЅР°РёРІРЅРѕРµ; РІ РѕС‚РІРµС‚ РґРѕР±Р°РІР»СЏРµРј `+05:00`.

        РРЅР°С‡Рµ РєР»РёРµРЅС‚ РІРїСЂР°РІРµ РїСЂРѕС‡РёС‚Р°С‚СЊ РјРµС‚РєСѓ РєР°Рє UTC Рё РїРѕРєР°Р·Р°С‚СЊ РµС‘ РЅР° РїСЏС‚СЊ
        С‡Р°СЃРѕРІ СЂР°РЅСЊС€Рµ.
        """
        return as_almaty(value)


class HealthResponse(BaseModel):
    """РћС‚РІРµС‚ GET /api/health."""

    status: str = "ok"
    version: str
