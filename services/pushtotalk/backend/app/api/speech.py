"""Р­РЅРґРїРѕРёРЅС‚С‹ РїСЂРёС‘РјР° СЂРµС‡Рё Рё РїСЂРѕСЃРјРѕС‚СЂР° РёСЃС‚РѕСЂРёРё."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database.database import get_session
from app.schemas.speech import (
    ErrorResponse,
    MessageResponse,
    SpeechRequest,
    SpeechResponse,
    TranscriptionResponse,
)
from app.services import speech_service
from app.services.kms_client import KmsForwardError, forward_text_command
from app.services.speech_service import SpeechValidationError
from app.services.transcription_service import (
    TranscriptionError,
    TranscriptionUnavailableError,
    transcribe_audio,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["speech"])

ALLOWED_AUDIO_EXTENSIONS = {".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".ogg", ".wav", ".webm"}


@router.post(
    "/speech",
    response_model=SpeechResponse,
    responses={400: {"model": ErrorResponse}},
    summary="РџСЂРёРЅСЏС‚СЊ СЂР°СЃРїРѕР·РЅР°РЅРЅС‹Р№ С‚РµРєСЃС‚",
)
def receive_speech(
    request: SpeechRequest,
    session: Session = Depends(get_session),
) -> SpeechResponse | JSONResponse:
    """РЎРѕС…СЂР°РЅСЏРµС‚ СЂРµРїР»РёРєСѓ Рё РІРѕР·РІСЂР°С‰Р°РµС‚ РµС‘ РёРґРµРЅС‚РёС„РёРєР°С‚РѕСЂ.

    РџСѓСЃС‚РѕР№ РёР»Рё СЃР»РёС€РєРѕРј РґР»РёРЅРЅС‹Р№ С‚РµРєСЃС‚ вЂ” РѕР¶РёРґР°РµРјР°СЏ СЃРёС‚СѓР°С†РёСЏ, Р° РЅРµ СЃР±РѕР№:
    РѕС‚РІРµС‡Р°РµРј 400 СЃ РѕРїРёСЃР°РЅРёРµРј, РЅРёС‡РµРіРѕ РЅРµ СЃРѕС…СЂР°РЅСЏСЏ.
    """
    try:
        message = speech_service.save_message(session, request.text, settings)
    except SpeechValidationError as error:
        logger.warning(
            "POST /api/speech РѕС‚РєР»РѕРЅС‘РЅ text_length=%s reason=%s",
            len(request.text),
            error,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ErrorResponse(message=str(error)).model_dump(),
        )

    try:
        forward_text_command(message.text, client_request_id=f"speech-{message.id}")
    except KmsForwardError as error:
        logger.warning("KMS forwarding failed for speech_message_id=%s: %s", message.id, error)

    return SpeechResponse(status="ok", id=message.id)


@router.post(
    "/speech/transcribe",
    response_model=TranscriptionResponse,
    responses={
        400: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Р Р°СЃРїРѕР·РЅР°С‚СЊ Р°СѓРґРёРѕ Р»РѕРєР°Р»СЊРЅС‹Рј Whisper",
)
def transcribe_speech(
    file: UploadFile = File(...),
) -> TranscriptionResponse | JSONResponse:
    """РџСЂРёРЅРёРјР°РµС‚ Р°СѓРґРёРѕС„Р°Р№Р», СЂР°СЃРїРѕР·РЅР°С‘С‚ РµРіРѕ Р»РѕРєР°Р»СЊРЅС‹Рј faster-whisper Рё РІРѕР·РІСЂР°С‰Р°РµС‚ С‚РµРєСЃС‚."""
    suffix = Path(file.filename or "speech.m4a").suffix.lower() or ".m4a"
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ErrorResponse(message=f"unsupported audio format: {suffix}").model_dump(),
        )

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
            shutil.copyfileobj(file.file, tmp)

        text = transcribe_audio(tmp_path)
    except TranscriptionUnavailableError as error:
        logger.exception("Whisper РЅРµРґРѕСЃС‚СѓРїРµРЅ")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorResponse(message=str(error)).model_dump(),
        )
    except TranscriptionError as error:
        logger.warning("РђСѓРґРёРѕ РЅРµ СЂР°СЃРїРѕР·РЅР°РЅРѕ: %s", error)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ErrorResponse(message=str(error)).model_dump(),
        )
    finally:
        file.file.close()
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    try:
        forward_text_command(text, source="pushtotalk-whisper")
    except KmsForwardError as error:
        logger.warning("KMS forwarding failed after transcription: %s", error)

    return TranscriptionResponse(status="ok", text=text)


@router.get(
    "/messages",
    response_model=list[MessageResponse],
    summary="РџРѕСЃР»РµРґРЅРёРµ СЃРѕРѕР±С‰РµРЅРёСЏ",
)
def list_messages(
    session: Session = Depends(get_session),
    limit: int = Query(default=settings.history_limit, ge=1, le=settings.history_limit),
) -> list[MessageResponse]:
    """РСЃС‚РѕСЂРёСЏ РґР»СЏ РїСЂРѕРІРµСЂРєРё С‚РѕРіРѕ, С‡С‚Рѕ РєР»РёРµРЅС‚ РґРµР№СЃС‚РІРёС‚РµР»СЊРЅРѕ РґРѕСЃС‚Р°РІР»СЏРµС‚ РґР°РЅРЅС‹Рµ."""
    messages = speech_service.recent_messages(session, limit, settings)
    return [MessageResponse.model_validate(message) for message in messages]
