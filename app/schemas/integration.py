from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import Base


class ImportError_(Base):
    """One rejected row. ``code`` is stable and safe to branch on."""

    event_id: str = ""
    code: Literal[
        "MISSING_EVENT_ID",
        "MISSING_CASE_ID",
        "MISSING_ACTIVITY",
        "INVALID_TIMESTAMP",
    ]
    message: str


class ImportResponse(Base):
    status: Literal["accepted", "partially_accepted"]
    export_id: str
    received: int
    accepted: int = Field(0, description="Rows stored by this call")
    duplicates: int = Field(0, description="Rows whose event_id was already known")
    rejected: int = Field(0, description="Rows that failed validation")
    errors: list[ImportError_] = Field(default_factory=list)
    log_ids: list[str] = Field(
        default_factory=list, description="Logs the batch landed in, one per case_type"
    )
