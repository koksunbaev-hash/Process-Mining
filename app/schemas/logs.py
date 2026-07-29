from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from app.schemas.common import Base


class EventIn(Base):
    """One raw event. ``activity`` may be free text - the mapping profile normalizes it."""

    event_id: str | None = Field(
        None,
        max_length=128,
        description="Stable id from the source system. Supplying it makes delivery "
        "idempotent: re-sending the same event is ignored instead of duplicated.",
    )
    case_id: str = Field(..., min_length=1, max_length=256, description="Process instance id")
    activity: str = Field(..., min_length=1, max_length=512)
    timestamp: datetime | None = Field(None, description="ISO-8601. Defaults to server time (UTC)")
    resource: str | None = Field(None, max_length=256, description="Who/what executed the step")
    lifecycle: str | None = Field(None, max_length=64, description="start / complete / ...")
    attributes: dict[str, Any] = Field(default_factory=dict, description="Free-form extras")


class ColumnMapping(Base):
    """Tells the service which CSV columns carry the mandatory process-mining fields."""

    case_id: str | None = None
    activity: str | None = None
    timestamp: str | None = None
    resource: str | None = None
    lifecycle: str | None = None
    timestamp_format: str | None = Field(None, description="strptime format, e.g. %d.%m.%Y %H:%M")
    separator: str | None = Field(None, description="CSV delimiter. Auto-sniffed when omitted")
    encoding: str = "utf-8"


class CreateLogRequest(Base):
    name: str = Field("untitled", max_length=200)
    events: list[EventIn] = Field(default_factory=list)
    mapping_profile: str | None = Field(None, description="Activity normalization profile id")
    tenant: str | None = Field(None, max_length=128, description="Logical owner / project")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _non_empty(self) -> CreateLogRequest:
        if not self.events:
            raise ValueError("events must not be empty")
        return self


class AppendEventsRequest(Base):
    events: list[EventIn] = Field(..., min_length=1)
    mapping_profile: str | None = None


class ActivityStat(Base):
    activity: str
    occurrences: int
    cases: int
    mean_duration_seconds: float | None = None


class LogSummary(Base):
    log_id: str
    name: str
    tenant: str | None = None
    events: int
    cases: int
    activities: int
    resources: int
    variants: int
    start_time: datetime | None = None
    end_time: datetime | None = None
    mapping_profile: str | None = None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventOut(Base):
    case_id: str
    activity: str
    activity_raw: str | None = None
    timestamp: datetime
    resource: str | None = None
    lifecycle: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class UploadResponse(Base):
    log: LogSummary
    detected_columns: dict[str, str | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class MappingProfileOut(Base):
    id: str
    description: str = ""
    fallback: str = "other_activity"
    rules: int = 0
    activities: list[str] = Field(default_factory=list)
