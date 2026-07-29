"""Storage contract.

The API layer never touches a database. It talks to :class:`LogRepository`,
which has two implementations today (in-memory, SQLite) and can grow a
Postgres/S3 one tomorrow without a single change upstream.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from app.core import model


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(slots=True)
class LogRecord:
    log_id: str
    name: str
    frame: pd.DataFrame
    tenant: str | None = None
    mapping_profile: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def summary(self) -> dict[str, Any]:
        frame = self.frame
        if frame.empty:
            counts = {"events": 0, "cases": 0, "activities": 0, "resources": 0, "variants": 0}
            start = end = None
        else:
            counts = {
                "events": int(len(frame)),
                "cases": int(frame[model.CASE].nunique()),
                "activities": int(frame[model.ACTIVITY].nunique()),
                "resources": int(frame[model.RESOURCE].nunique(dropna=True)),
                "variants": int(
                    frame.groupby(model.CASE, sort=False)[model.ACTIVITY].apply(tuple).nunique()
                ),
            }
            start = frame[model.TIMESTAMP].min()
            end = frame[model.TIMESTAMP].max()
        return {
            "log_id": self.log_id,
            "name": self.name,
            "tenant": self.tenant,
            **counts,
            "start_time": start,
            "end_time": end,
            "mapping_profile": self.mapping_profile,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


class LogRepository(abc.ABC):
    @abc.abstractmethod
    def create(self, record: LogRecord) -> LogRecord: ...

    @abc.abstractmethod
    def get(self, log_id: str, tenant: str | None = None) -> LogRecord | None: ...

    @abc.abstractmethod
    def append(self, log_id: str, frame: pd.DataFrame, tenant: str | None = None) -> LogRecord: ...

    @abc.abstractmethod
    def list(
        self, *, tenant: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[LogRecord], int]: ...

    @abc.abstractmethod
    def delete(self, log_id: str, tenant: str | None = None) -> bool: ...

    # ---- idempotent ingestion -------------------------------------------
    # Both default to "I know nothing", so a backend that does not care about
    # replay protection stays valid: it simply never reports a duplicate.

    def known_event_ids(self, log_id: str, event_ids: list[str]) -> set[str]:
        """Subset of ``event_ids`` already stored in this log."""
        return set()

    def get_receipt(self, key: str) -> dict[str, Any] | None:
        """The stored answer for an already-processed idempotency key."""
        return None

    def save_receipt(self, key: str, payload: dict[str, Any]) -> None:
        """Remembers the answer, so replaying a batch replays its response."""
        return None

    def health(self) -> dict[str, Any]:
        return {"backend": type(self).__name__, "ok": True}
