"""Event-log lifecycle endpoints."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.deps import ApiKeyDep, LogServiceDep
from app.errors import NotFoundError, ValidationError
from app.schemas.common import Page
from app.schemas.logs import (
    AppendEventsRequest,
    ColumnMapping,
    CreateLogRequest,
    EventOut,
    LogSummary,
    UploadResponse,
)
from app.services.log_service import summarize

router = APIRouter(prefix="/logs", tags=["logs"])


def _parse_columns(raw: str | None) -> ColumnMapping:
    if not raw:
        return ColumnMapping()
    try:
        return ColumnMapping.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(f"'columns' must be a valid JSON object: {exc}") from exc


@router.post(
    "",
    response_model=LogSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a log from a JSON list of events",
)
async def create_log(payload: CreateLogRequest, service: LogServiceDep, _: ApiKeyDep) -> Any:
    record = service.create_from_events(payload)
    return summarize(record)


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a log from a CSV / TSV / XES / JSON file",
)
async def upload_log(
    service: LogServiceDep,
    _: ApiKeyDep,
    file: Annotated[UploadFile, File(description="CSV, TSV, XES(.gz), JSON or JSONL")],
    name: Annotated[str | None, Form()] = None,
    tenant: Annotated[str | None, Form()] = None,
    mapping_profile: Annotated[str | None, Form()] = None,
    columns: Annotated[
        str | None, Form(description='JSON, e.g. {"case_id":"batch","activity":"step"}')
    ] = None,
) -> Any:
    payload = await file.read()
    record, result = service.create_from_upload(
        payload=payload,
        filename=file.filename or "upload.csv",
        name=name,
        tenant=tenant,
        mapping_profile=mapping_profile,
        columns=_parse_columns(columns),
    )
    return {
        "log": summarize(record),
        "detected_columns": result.detected_columns,
        "warnings": result.warnings,
    }


@router.post("/preview", summary="Inspect a file's columns without importing it")
async def preview(
    _: ApiKeyDep,
    file: Annotated[UploadFile, File()],
    rows: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict[str, Any]:
    from app.core.ingestion import preview_columns

    payload = await file.read()
    return preview_columns(payload, file.filename or "upload.csv", rows=rows)


@router.get("", response_model=Page[LogSummary], summary="List logs")
async def list_logs(
    service: LogServiceDep,
    _: ApiKeyDep,
    tenant: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Any:
    items, total = service.list(tenant=tenant, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{log_id}", response_model=LogSummary, summary="Get one log's summary")
async def get_log(log_id: str, service: LogServiceDep, _: ApiKeyDep, tenant: str | None = None) -> Any:
    return summarize(service.require(log_id, tenant))


@router.get("/{log_id}/events", response_model=Page[EventOut], summary="Page through raw events")
async def get_events(
    log_id: str,
    service: LogServiceDep,
    _: ApiKeyDep,
    limit: Annotated[int, Query(ge=1, le=5000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    tenant: str | None = None,
) -> Any:
    items, total = service.events_page(log_id, limit=limit, offset=offset, tenant=tenant)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post(
    "/{log_id}/events",
    response_model=LogSummary,
    summary="Append events (this is how a voice/IoT/ERP client streams data in)",
)
async def append_events(
    log_id: str,
    payload: AppendEventsRequest,
    service: LogServiceDep,
    _: ApiKeyDep,
    tenant: str | None = None,
) -> Any:
    return summarize(service.append_events(log_id, payload, tenant))


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a log")
async def delete_log(
    log_id: str, service: LogServiceDep, _: ApiKeyDep, tenant: str | None = None
) -> None:
    if not service.delete(log_id, tenant):
        raise NotFoundError(f"Log '{log_id}' not found")
