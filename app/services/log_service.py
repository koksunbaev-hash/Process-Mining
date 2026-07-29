"""Use-cases around event logs: create, append, read, delete.

The API layer stays dumb (validate -> call -> serialize); everything that could
be reused by a CLI, a worker or a gRPC front-end lives here.
"""

from __future__ import annotations

import uuid
from typing import Any

import pandas as pd

from app.config import Settings
from app.core import ingestion, model
from app.core.cache import TTLCache
from app.core.mapping import MappingRegistry
from app.errors import NotFoundError, PayloadTooLargeError, ValidationError
from app.logging_config import get_logger
from app.schemas.logs import AppendEventsRequest, ColumnMapping, CreateLogRequest, EventIn
from app.storage.base import LogRecord, LogRepository, utcnow

log = get_logger(__name__)


class LogService:
    def __init__(
        self,
        repository: LogRepository,
        mappings: MappingRegistry,
        settings: Settings,
        cache: TTLCache,
    ) -> None:
        self.repository = repository
        self.mappings = mappings
        self.settings = settings
        self.cache = cache

    # ---- creation ------------------------------------------------------
    def create_from_events(self, request: CreateLogRequest) -> LogRecord:
        profile = self.mappings.get(request.mapping_profile)
        frame = ingestion.events_to_frame(request.events, profile=profile)
        self._guard_size(frame)
        record = LogRecord(
            log_id=_new_id(),
            name=request.name,
            tenant=request.tenant,
            mapping_profile=profile.id,
            metadata=request.metadata,
            frame=frame,
        )
        return self.repository.create(record)

    def create_from_upload(
        self,
        *,
        payload: bytes,
        filename: str,
        name: str | None = None,
        tenant: str | None = None,
        mapping_profile: str | None = None,
        columns: ColumnMapping | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[LogRecord, ingestion.IngestionResult]:
        if len(payload) > self.settings.max_upload_bytes:
            raise PayloadTooLargeError(
                f"File is larger than {self.settings.max_upload_mb} MB"
            )
        columns = columns or ColumnMapping()
        raw = ingestion.read_upload(
            payload,
            filename,
            encoding=columns.encoding,
            separator=columns.separator,
        )
        profile = self.mappings.get(mapping_profile)
        result = ingestion.to_canonical(
            raw,
            profile=profile,
            mapping={
                model.CASE: columns.case_id,
                model.ACTIVITY: columns.activity,
                model.TIMESTAMP: columns.timestamp,
                model.RESOURCE: columns.resource,
                model.LIFECYCLE: columns.lifecycle,
            },
            timestamp_format=columns.timestamp_format,
        )
        self._guard_size(result.frame)
        record = LogRecord(
            log_id=_new_id(),
            name=name or filename or "uploaded log",
            tenant=tenant,
            mapping_profile=profile.id,
            metadata={"source_file": filename, **(metadata or {})},
            frame=result.frame,
        )
        self.repository.create(record)
        return record, result

    def frame_from_upload(
        self,
        *,
        payload: bytes,
        filename: str,
        mapping_profile: str | None = None,
        columns: ColumnMapping | None = None,
    ) -> ingestion.IngestionResult:
        """Stateless path: parse and return, never persist."""
        if len(payload) > self.settings.max_upload_bytes:
            raise PayloadTooLargeError(f"File is larger than {self.settings.max_upload_mb} MB")
        columns = columns or ColumnMapping()
        raw = ingestion.read_upload(
            payload, filename, encoding=columns.encoding, separator=columns.separator
        )
        profile = self.mappings.get(mapping_profile)
        result = ingestion.to_canonical(
            raw,
            profile=profile,
            mapping={
                model.CASE: columns.case_id,
                model.ACTIVITY: columns.activity,
                model.TIMESTAMP: columns.timestamp,
                model.RESOURCE: columns.resource,
                model.LIFECYCLE: columns.lifecycle,
            },
            timestamp_format=columns.timestamp_format,
        )
        self._guard_size(result.frame)
        return result

    # ---- mutation ------------------------------------------------------
    def append_events(
        self, log_id: str, request: AppendEventsRequest, tenant: str | None = None
    ) -> LogRecord:
        record = self.require(log_id, tenant)
        profile = self.mappings.get(request.mapping_profile or record.mapping_profile)
        frame = ingestion.events_to_frame(request.events, profile=profile)
        updated = self.repository.append(log_id, frame, tenant)
        self.cache.invalidate_prefix(log_id)
        updated.updated_at = utcnow()
        return updated

    def delete(self, log_id: str, tenant: str | None = None) -> bool:
        self.cache.invalidate_prefix(log_id)
        return self.repository.delete(log_id, tenant)

    # ---- reads ---------------------------------------------------------
    def require(self, log_id: str, tenant: str | None = None) -> LogRecord:
        record = self.repository.get(log_id, tenant)
        if record is None:
            raise NotFoundError(f"Log '{log_id}' not found")
        return record

    def list(
        self, *, tenant: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        records, total = self.repository.list(tenant=tenant, limit=limit, offset=offset)
        return [summarize(record) for record in records], total

    def events_page(
        self, log_id: str, *, limit: int = 100, offset: int = 0, tenant: str | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        record = self.require(log_id, tenant)
        frame = record.frame
        total = int(len(frame))
        window = frame.iloc[offset : offset + limit]
        extras = [c for c in frame.columns if c not in model.CANONICAL_COLUMNS]
        items: list[dict[str, Any]] = []
        for row in window.to_dict(orient="records"):
            items.append(
                {
                    "case_id": row[model.CASE],
                    "activity": row[model.ACTIVITY],
                    "activity_raw": row.get(model.ACTIVITY_RAW),
                    "timestamp": row[model.TIMESTAMP],
                    "resource": row.get(model.RESOURCE),
                    "lifecycle": row.get(model.LIFECYCLE),
                    "attributes": {k: row[k] for k in extras if pd.notna(row.get(k))},
                }
            )
        return items, total

    # ---- guards --------------------------------------------------------
    def _guard_size(self, frame: pd.DataFrame) -> None:
        if len(frame) > self.settings.max_events_per_log:
            raise ValidationError(
                f"Log has {len(frame)} events, limit is {self.settings.max_events_per_log}"
            )


def summarize(record: LogRecord) -> dict[str, Any]:
    """Uses cheap SQL counters when the repository provided them."""
    summary = record.summary()
    counts = (record.metadata or {}).get("_counts")
    if counts:
        summary.update({k: v for k, v in counts.items() if v is not None})
        summary["metadata"] = {k: v for k, v in record.metadata.items() if k != "_counts"}
    return summary


def _new_id() -> str:
    return uuid.uuid4().hex[:20]


def events_from_payload(events: list[EventIn]) -> list[EventIn]:
    return events
