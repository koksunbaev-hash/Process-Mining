from __future__ import annotations

from app.config import Settings
from app.storage.base import LogRecord, LogRepository
from app.storage.memory import InMemoryLogRepository


def build_repository(settings: Settings) -> LogRepository:
    if settings.storage_backend == "sqlite":
        from app.storage.sqlite import SqliteLogRepository

        return SqliteLogRepository(settings.sqlite_path)
    return InMemoryLogRepository()


__all__ = ["LogRecord", "LogRepository", "InMemoryLogRepository", "build_repository"]
