"""Voice intake for source systems.

The contract, in one paragraph: take the recording, answer at once with a task
id, transcribe in the background, then POST the result back signed. The caller
never waits on a model, and a slow transcription cannot time out its request.

This service returns text and nothing else. Turning "партия B-154 закончила
замес" into a state change is the source system's job - it owns the business
rules, the permissions and the consequences.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.deps import ApiKeyDep, JobManagerDep
from app.errors import (
    PayloadTooLargeError,
    SpeechUnavailableError,
    UnsupportedFormatError,
    ValidationError,
)
from app.logging_config import get_logger
from app.services.stt import SttError, new_task_id

log = get_logger(__name__)

router = APIRouter(prefix="/transcriptions", tags=["voice"])


def _run(app_state: Any, *, task_id: str, external_id: str, payload: bytes,
         language: str, callback_url: str, context: dict[str, Any]) -> dict[str, Any]:
    """Background half: transcribe, then deliver the verdict."""
    stt = app_state.stt_service
    try:
        result = stt.transcribe(payload, language=language)
        body = {
            "task_id": task_id,
            "external_id": external_id,
            "status": "completed",
            "transcript": result["transcript"],
            # The plugin does not expose a per-utterance score; report the
            # value the contract expects rather than inventing a number.
            "confidence": None,
            "language": result["language"],
            "duration_ms": result["duration_ms"],
        }
    except SttError as exc:
        log.warning("transcription_failed", extra={"task": task_id, "code": exc.code})
        body = {
            "task_id": task_id,
            "external_id": external_id,
            "status": "failed",
            "error_code": exc.code,
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001 - never leave the caller hanging
        log.exception("transcription_crashed", extra={"task": task_id})
        body = {
            "task_id": task_id,
            "external_id": external_id,
            "status": "failed",
            "error_code": "INTERNAL_ERROR",
            "error": f"{type(exc).__name__}: {exc}",
        }

    stt.send_callback(callback_url, body)
    return body


@router.post(
    "/",
    summary="Submit a recording for transcription; the result arrives by callback",
)
async def create_transcription(
    request: Request,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    audio_file: Annotated[UploadFile, File(description="webm / ogg / mp3 / wav / mp4")],
    external_id: Annotated[str, Form(description="Caller's id for this recording")],
    client_request_id: Annotated[str, Form(description="Idempotency key")] = "",
    callback_url: Annotated[str, Form(description="Absolute URL to POST the result to")] = "",
    # Empty rather than "ru": a caller that says nothing about language gets
    # PM_STT_LANGUAGE, which is where this deployment's answer lives. A default
    # here silently outranked that setting.
    language: Annotated[str, Form()] = "",
    context: Annotated[str, Form(description="JSON hints: stages, batch_numbers")] = "",
) -> dict[str, Any]:
    settings = request.app.state.settings
    repository = request.app.state.repository

    payload = await audio_file.read()
    if len(payload) > settings.max_upload_bytes:
        raise PayloadTooLargeError(f"Audio is larger than {settings.max_upload_mb} MB")

    # Same recording submitted twice returns the same task instead of running
    # the model again - the contract asks for it, and retries are cheap to
    # trigger from a flaky phone connection.
    receipt_key = f"stt:{client_request_id}" if client_request_id else ""
    if receipt_key:
        previous = repository.get_receipt(receipt_key)
        if previous is not None:
            log.info("transcription_replayed", extra={"external_id": external_id})
            return previous

    hints: dict[str, Any] = {}
    if context:
        try:
            parsed = json.loads(context)
            if isinstance(parsed, dict):
                hints = parsed
        except json.JSONDecodeError:
            log.warning("transcription_context_unparsable", extra={"external_id": external_id})

    task_id = new_task_id()
    accepted = {"task_id": task_id, "external_id": external_id, "status": "processing"}
    if receipt_key:
        repository.save_receipt(receipt_key, accepted)

    app_state = request.app.state
    jobs.submit(
        f"transcribe:{external_id}",
        lambda: _run(
            app_state,
            task_id=task_id,
            external_id=external_id,
            payload=payload,
            language=language,
            callback_url=callback_url,
            context=hints,
        ),
    )

    log.info(
        "transcription_accepted",
        extra={"task": task_id, "external_id": external_id, "bytes": len(payload)},
    )
    return accepted


# Errors from the speech path, mapped once. A caller retries a 503 and fixes a
# 415 - anything that blurs the two makes the phone app retry forever.
_STT_ERRORS = {
    "STT_UNAVAILABLE": SpeechUnavailableError,
    "AUDIO_DECODE_UNAVAILABLE": SpeechUnavailableError,
    "UNSUPPORTED_AUDIO": UnsupportedFormatError,
}


@router.post(
    "/sync",
    summary="Transcribe a recording and answer with the text, no callback",
)
async def transcribe_sync(
    request: Request,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    audio_file: Annotated[UploadFile, File(description="webm / ogg / mp3 / wav / mp4 / m4a")],
    language: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    """The same speech container the web console uses, answered inline.

    The callback flow above exists because a browser recording arrives from a
    page that must stay responsive. A phone holding a push-to-talk button has
    nowhere to receive a callback and is already waiting, so it gets the text
    on the same connection - one model in the stack instead of two.
    """
    settings = request.app.state.settings
    stt = request.app.state.stt_service

    payload = await audio_file.read()
    if len(payload) > settings.max_upload_bytes:
        raise PayloadTooLargeError(f"Audio is larger than {settings.max_upload_mb} MB")

    try:
        # Decoding and the model are both blocking; on the event loop they
        # would stall every other request for the length of the recording.
        result = await jobs.run_blocking(
            stt.transcribe, payload, language=language or None
        )
    except SttError as exc:
        log.warning("transcribe_sync_failed", extra={"code": exc.code})
        raise _STT_ERRORS.get(exc.code, ValidationError)(str(exc)) from exc

    log.info(
        "transcribe_sync_done",
        extra={"chars": len(result["transcript"]), "took_ms": result["took_ms"]},
    )
    return {"status": "ok", "text": result["transcript"], **result}


@router.get("/capabilities", summary="Formats and limits this service accepts")
async def capabilities(request: Request, _: ApiKeyDep) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "formats": ["audio/webm", "audio/ogg", "audio/mpeg", "audio/wav", "audio/mp4"],
        "max_file_size_mb": settings.max_upload_mb,
        "max_duration_seconds": settings.max_audio_seconds,
        "sample_rate": settings.stt_sample_rate,
        "languages": [settings.stt_language],
        "callback_signature": "HMAC-SHA256 over the raw body, header X-Process-Mining-Signature: sha256=<hex>",
        "error_codes": [
            "UNSUPPORTED_AUDIO", "EMPTY_AUDIO", "EMPTY_TRANSCRIPT",
            "AUDIO_DECODE_TIMEOUT", "AUDIO_DECODE_UNAVAILABLE",
            "STT_UNAVAILABLE", "TRANSCRIPTION_FAILED", "INTERNAL_ERROR",
        ],
    }
