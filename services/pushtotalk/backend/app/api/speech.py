"""Эндпоинты приёма речи и просмотра истории."""

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
from app.services.mqtt_client import MqttPublishError, publish_text_command
from app.services.speech_service import SpeechValidationError
from app.services.transcription_service import (
    TranscriptionError,
    TranscriptionUnavailableError,
    transcribe_audio,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["speech"])

ALLOWED_AUDIO_EXTENSIONS = {".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".ogg", ".wav", ".webm"}


def dispatch_text_command(text: str, *, client_request_id: str | None = None, source: str = "pushtotalk") -> None:
    """Send recognized text to MQTT when configured, with direct KMS as fallback."""
    try:
        mqtt_result = publish_text_command(text, client_request_id=client_request_id, source=source)
    except MqttPublishError as error:
        logger.warning("MQTT publish failed; falling back to KMS: %s", error)
    else:
        if mqtt_result.get("status") != "skipped":
            return

    try:
        forward_text_command(text, client_request_id=client_request_id, source=source)
    except KmsForwardError as error:
        logger.error("KMS forwarding failed: %s", error)
        raise


@router.post(
    "/speech",
    response_model=SpeechResponse,
    responses={400: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
    summary="Принять распознанный текст",
)
def receive_speech(
    request: SpeechRequest,
    session: Session = Depends(get_session),
) -> SpeechResponse | JSONResponse:
    """Сохраняет реплику и возвращает её идентификатор.

    Пустой или слишком длинный текст — ожидаемая ситуация, а не сбой:
    отвечаем 400 с описанием, ничего не сохраняя.
    """
    try:
        message = speech_service.save_message(session, request.text, settings)
    except SpeechValidationError as error:
        logger.warning(
            "POST /api/speech отклонён text_length=%s reason=%s",
            len(request.text),
            error,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ErrorResponse(message=str(error)).model_dump(),
        )

    try:
        dispatch_text_command(message.text, client_request_id=f"speech-{message.id}")
    except KmsForwardError:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=ErrorResponse(message="KMS не принял текст. Повторите отправку.").model_dump(),
        )

    return SpeechResponse(status="ok", id=message.id)


@router.post(
    "/speech/transcribe",
    response_model=TranscriptionResponse,
    responses={
        400: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Распознать аудио локальным Whisper",
)
def transcribe_speech(
    file: UploadFile = File(...),
) -> TranscriptionResponse | JSONResponse:
    """Принимает аудиофайл, распознаёт его локальным faster-whisper и возвращает текст."""
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
        logger.exception("Whisper недоступен")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorResponse(message=str(error)).model_dump(),
        )
    except TranscriptionError as error:
        logger.warning("Аудио не распознано: %s", error)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ErrorResponse(message=str(error)).model_dump(),
        )
    finally:
        file.file.close()
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    return TranscriptionResponse(status="ok", text=text)


@router.get(
    "/messages",
    response_model=list[MessageResponse],
    summary="Последние сообщения",
)
def list_messages(
    session: Session = Depends(get_session),
    limit: int = Query(default=settings.history_limit, ge=1, le=settings.history_limit),
) -> list[MessageResponse]:
    """История для проверки того, что клиент действительно доставляет данные."""
    messages = speech_service.recent_messages(session, limit, settings)
    return [MessageResponse.model_validate(message) for message in messages]
