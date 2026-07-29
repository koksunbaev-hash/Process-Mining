"""SQLite-backed repository.

One container, one file, survives restarts - which was the prototype's biggest
weakness (everything lived in ``st.session_state``). Extra event attributes are
folded into a JSON column so a single table fits every project's schema.

Swapping to Postgres is a URL change: the code is plain SQLAlchemy Core.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)

from app.core import model
from app.errors import NotFoundError
from app.storage.base import LogRecord, LogRepository, utcnow

metadata_obj = MetaData()

logs_table = Table(
    "logs",
    metadata_obj,
    Column("log_id", String(64), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("tenant", String(128), nullable=True, index=True),
    Column("mapping_profile", String(128), nullable=True),
    Column("metadata_json", JSON, nullable=False, default=dict),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

events_table = Table(
    "events",
    metadata_obj,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("log_id", String(64), nullable=False),
    Column("case_id", String(256), nullable=False),
    Column("activity", String(512), nullable=False),
    Column("activity_raw", String(512), nullable=True),
    Column("timestamp", DateTime, nullable=False),
    Column("resource", String(256), nullable=True),
    Column("lifecycle", String(64), nullable=True),
    Column("attributes_json", JSON, nullable=True),
)
Index("ix_events_log_case", events_table.c.log_id, events_table.c.case_id)
Index("ix_events_log_ts", events_table.c.log_id, events_table.c.timestamp)

EXTRA_KEY = "attributes_json"


class SqliteLogRepository(LogRepository):
    def __init__(self, db_path: Path | str, *, echo: bool = False) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(
            f"sqlite:///{path}",
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        self._lock = threading.RLock()
        metadata_obj.create_all(self._engine)
        with self._engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL")

    # ---- helpers -------------------------------------------------------
    @staticmethod
    def _frame_to_rows(log_id: str, frame: pd.DataFrame) -> list[dict[str, Any]]:
        extras = [c for c in frame.columns if c not in model.CANONICAL_COLUMNS]
        rows: list[dict[str, Any]] = []
        for record in frame.to_dict(orient="records"):
            attributes = {k: record.get(k) for k in extras if pd.notna(record.get(k))}
            rows.append(
                {
                    "log_id": log_id,
                    "case_id": str(record[model.CASE]),
                    "activity": str(record[model.ACTIVITY]),
                    "activity_raw": record.get(model.ACTIVITY_RAW),
                    "timestamp": record[model.TIMESTAMP].to_pydatetime()
                    if isinstance(record[model.TIMESTAMP], pd.Timestamp)
                    else record[model.TIMESTAMP],
                    "resource": record.get(model.RESOURCE),
                    "lifecycle": record.get(model.LIFECYCLE),
                    "attributes_json": json.loads(json.dumps(attributes, default=str))
                    if attributes
                    else None,
                }
            )
        return rows

    def _load_frame(self, log_id: str) -> pd.DataFrame:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(
                    events_table.c.case_id,
                    events_table.c.activity,
                    events_table.c.activity_raw,
                    events_table.c.timestamp,
                    events_table.c.resource,
                    events_table.c.lifecycle,
                    events_table.c.attributes_json,
                )
                .where(events_table.c.log_id == log_id)
                .order_by(events_table.c.case_id, events_table.c.timestamp)
            ).mappings().all()

        if not rows:
            return model.empty_frame()

        records: list[dict[str, Any]] = []
        for row in rows:
            item = {
                model.CASE: row["case_id"],
                model.ACTIVITY: row["activity"],
                model.ACTIVITY_RAW: row["activity_raw"],
                model.TIMESTAMP: row["timestamp"],
                model.RESOURCE: row["resource"],
                model.LIFECYCLE: row["lifecycle"],
            }
            for key, value in (row["attributes_json"] or {}).items():
                item.setdefault(key, value)
            records.append(item)
        return model.normalize_dtypes(pd.DataFrame(records))

    @staticmethod
    def _row_to_record(row: Any, frame: pd.DataFrame) -> LogRecord:
        return LogRecord(
            log_id=row["log_id"],
            name=row["name"],
            tenant=row["tenant"],
            mapping_profile=row["mapping_profile"],
            metadata=row["metadata_json"] or {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            frame=frame,
        )

    # ---- repository API ------------------------------------------------
    def create(self, record: LogRecord) -> LogRecord:
        with self._lock, self._engine.begin() as conn:
            conn.execute(
                insert(logs_table).values(
                    log_id=record.log_id,
                    name=record.name,
                    tenant=record.tenant,
                    mapping_profile=record.mapping_profile,
                    metadata_json=record.metadata,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )
            rows = self._frame_to_rows(record.log_id, record.frame)
            if rows:
                conn.execute(insert(events_table), rows)
        return record

    def get(self, log_id: str, tenant: str | None = None) -> LogRecord | None:
        with self._engine.connect() as conn:
            query = select(logs_table).where(logs_table.c.log_id == log_id)
            if tenant:
                query = query.where(logs_table.c.tenant == tenant)
            row = conn.execute(query).mappings().first()
        if row is None:
            return None
        return self._row_to_record(row, self._load_frame(log_id))

    def append(self, log_id: str, frame: pd.DataFrame, tenant: str | None = None) -> LogRecord:
        record = self.get(log_id, tenant)
        if record is None:
            raise NotFoundError(f"Log '{log_id}' not found")
        now = utcnow()
        with self._lock, self._engine.begin() as conn:
            rows = self._frame_to_rows(log_id, frame)
            if rows:
                conn.execute(insert(events_table), rows)
            conn.execute(
                update(logs_table).where(logs_table.c.log_id == log_id).values(updated_at=now)
            )
        refreshed = self.get(log_id, tenant)
        assert refreshed is not None
        return refreshed

    def list(
        self, *, tenant: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[LogRecord], int]:
        with self._engine.connect() as conn:
            base = select(logs_table)
            counter = select(func.count()).select_from(logs_table)
            if tenant:
                base = base.where(logs_table.c.tenant == tenant)
                counter = counter.where(logs_table.c.tenant == tenant)
            total = int(conn.execute(counter).scalar_one())
            rows = (
                conn.execute(
                    base.order_by(logs_table.c.updated_at.desc()).limit(limit).offset(offset)
                )
                .mappings()
                .all()
            )
            summaries = []
            for row in rows:
                stats = conn.execute(
                    select(
                        func.count().label("events"),
                        func.count(func.distinct(events_table.c.case_id)).label("cases"),
                        func.count(func.distinct(events_table.c.activity)).label("activities"),
                        func.min(events_table.c.timestamp).label("start"),
                        func.max(events_table.c.timestamp).label("end"),
                    ).where(events_table.c.log_id == row["log_id"])
                ).mappings().first()
                lightweight = pd.DataFrame(
                    {
                        model.CASE: [],
                        model.ACTIVITY: [],
                        model.TIMESTAMP: [],
                    }
                )
                record = self._row_to_record(row, model.normalize_dtypes(lightweight))
                record.metadata = {
                    **(record.metadata or {}),
                    "_counts": {
                        "events": int(stats["events"] or 0),
                        "cases": int(stats["cases"] or 0),
                        "activities": int(stats["activities"] or 0),
                        "start_time": stats["start"],
                        "end_time": stats["end"],
                    },
                }
                summaries.append(record)
        return summaries, total

    def delete(self, log_id: str, tenant: str | None = None) -> bool:
        record = self.get(log_id, tenant)
        if record is None:
            return False
        with self._lock, self._engine.begin() as conn:
            conn.execute(delete(events_table).where(events_table.c.log_id == log_id))
            conn.execute(delete(logs_table).where(logs_table.c.log_id == log_id))
        return True

    def health(self) -> dict[str, Any]:
        try:
            with self._engine.connect() as conn:
                logs = int(conn.execute(select(func.count()).select_from(logs_table)).scalar_one())
                events = int(
                    conn.execute(select(func.count()).select_from(events_table)).scalar_one()
                )
            return {"backend": "sqlite", "ok": True, "logs": logs, "events": events}
        except Exception as exc:  # pragma: no cover
            return {"backend": "sqlite", "ok": False, "error": str(exc)}


__all__ = ["SqliteLogRepository", "datetime"]
