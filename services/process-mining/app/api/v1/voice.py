"""Optional voice endpoints. Disabled unless PM_VOICE_ENABLED=true."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.deps import ApiKeyDep, JobManagerDep, LogServiceDep
from app.errors import PayloadTooLargeError
from app.schemas.logs import AppendEventsRequest, EventIn
from app.schemas.mining import TranscriptionResponse
from app.services.log_service import summarize

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post(
    "/transcribe",
    response_model=TranscriptionResponse,
    summary="Audio -> text -> normalized activity",
)
async def transcribe(
    request: Request,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    file: Annotated[UploadFile, File(description="wav / mp3 / m4a / ogg / flac / webm")],
    language: Annotated[str | None, Form()] = None,
    mapping_profile: Annotated[str | None, Form()] = None,
) -> Any:
    settings = request.app.state.settings
    payload = await file.read()
    if len(payload) > settings.max_upload_bytes:
        raise PayloadTooLargeError(f"Audio is larger than {settings.max_upload_mb} MB")

    service = request.app.state.transcription_service
    return await jobs.run_blocking(
        service.transcribe,
        payload,
        file.filename or "audio.wav",
        language=language,
        mapping_profile=mapping_profile,
    )


@router.post(
    "/logs/{log_id}/events",
    summary="Transcribe an utterance and append it to a log in one call",
)
async def transcribe_and_append(
    log_id: str,
    request: Request,
    logs: LogServiceDep,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    file: Annotated[UploadFile, File()],
    case_id: Annotated[str, Form(description="Batch / order / ticket id")],
    resource: Annotated[str | None, Form(description="Operator name")] = None,
    language: Annotated[str | None, Form()] = None,
    tenant: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    record = logs.require(log_id, tenant)
    service = request.app.state.transcription_service
    payload = await file.read()

    result = await jobs.run_blocking(
        service.transcribe,
        payload,
        file.filename or "audio.wav",
        language=language,
        mapping_profile=record.mapping_profile,
    )

    updated = logs.append_events(
        log_id,
        AppendEventsRequest(
            events=[
                EventIn(
                    case_id=case_id,
                    activity=result["text"] or "unknown",
                    resource=resource,
                    attributes={
                        "source": "voice",
                        "transcript": result["text"],
                        "matched_rule": result.get("matched_rule"),
                    },
                )
            ]
        ),
        tenant,
    )
    return {"transcription": result, "log": summarize(updated)}
