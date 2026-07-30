"""In-memory repository: zero setup, perfect for tests and stateless mode."""

from __future__ import annotations

import threading
from typing import Any

import pandas as pd

from app.core import model
from app.errors import NotFoundError
from app.storage.base import LogRecord, LogRepository, utcnow


class InMemoryLogRepository(LogRepository):
    def __init__(self) -> None:
        self._items: dict[str, LogRecord] = {}
        self._receipts: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def create(self, record: LogRecord) -> LogRecord:
        with self._lock:
            self._items[record.log_id] = record
            return record

    def get(self, log_id: str, tenant: str | None = None) -> LogRecord | None:
        with self._lock:
            record = self._items.get(log_id)
            if record and tenant and record.tenant != tenant:
                return None
            return record

    def append(self, log_id: str, frame: pd.DataFrame, tenant: str | None = None) -> LogRecord:
        with self._lock:
            record = self.get(log_id, tenant)
            if record is None:
                raise NotFoundError(f"Log '{log_id}' not found")
            merged = pd.concat([record.frame, frame], ignore_index=True)
            record.frame = model.normalize_dtypes(merged)
            record.updated_at = utcnow()
            return record

    def list(
        self, *, tenant: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[LogRecord], int]:
        with self._lock:
            values = [r for r in self._items.values() if not tenant or r.tenant == tenant]
            values.sort(key=lambda r: r.updated_at, reverse=True)
            return values[offset : offset + limit], len(values)

    def delete(self, log_id: str, tenant: str | None = None) -> bool:
        with self._lock:
            record = self.get(log_id, tenant)
            if record is None:
                return False
            self._items.pop(log_id, None)
            return True

    # ---- idempotent ingestion -------------------------------------------
    def known_event_ids(self, log_id: str, event_ids: list[str]) -> set[str]:
        with self._lock:
            record = self._items.get(log_id)
            if record is None or record.frame.empty:
                return set()
            stored = {v for v in record.frame[model.EVENT_ID].tolist() if v}
            return stored.intersection(e for e in event_ids if e)

    def get_receipt(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._receipts.get(key)
            return dict(payload) if payload else None

    def save_receipt(self, key: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._receipts[key] = dict(payload)
