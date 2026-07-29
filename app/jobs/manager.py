"""Background job manager.

Discovery on a million-event log takes seconds to minutes. Blocking an HTTP
worker for that is how you get gateway timeouts, so heavy calls can be run
asynchronously: POST returns ``202 + job_id``, the client polls
``GET /jobs/{id}``.

CPU-bound pm4py work runs in a thread pool, never on the event loop.
For multi-replica deployments swap this class for Celery/RQ - the API contract
stays identical.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.errors import NotFoundError
from app.logging_config import get_logger
from app.storage.base import utcnow

log = get_logger(__name__)


@dataclass
class Job:
    job_id: str
    kind: str
    status: str = "queued"
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: float = 0.0
    result: dict[str, Any] | None = None
    error: str | None = None


class JobManager:
    def __init__(self, *, max_workers: int = 4, ttl_seconds: int = 3600) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pm-job")
        self._ttl = timedelta(seconds=ttl_seconds)

    async def run_blocking(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Runs CPU-bound work off the event loop, awaited inline (sync endpoints)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: func(*args, **kwargs))

    def submit(self, kind: str, func: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> Job:
        job = Job(job_id=uuid.uuid4().hex[:20], kind=kind)
        with self._lock:
            self._prune()
            self._jobs[job.job_id] = job

        def runner() -> None:
            job.status = "running"
            job.started_at = utcnow()
            try:
                job.result = func(*args, **kwargs)
                job.status = "succeeded"
                job.progress = 1.0
            except Exception as exc:  # noqa: BLE001 - surfaced through the job record
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                log.exception("job_failed", extra={"job_id": job.job_id, "kind": kind})
            finally:
                job.finished_at = utcnow()

        self._executor.submit(runner)
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise NotFoundError(f"Job '{job_id}' not found or expired")
            return job

    def list(self, limit: int = 50) -> list[Job]:
        with self._lock:
            self._prune()
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]

    def _prune(self) -> None:
        deadline = utcnow() - self._ttl
        for job_id, job in list(self._jobs.items()):
            if job.finished_at and job.finished_at < deadline:
                self._jobs.pop(job_id, None)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def stats(self) -> dict[str, int]:
        with self._lock:
            counter: dict[str, int] = {}
            for job in self._jobs.values():
                counter[job.status] = counter.get(job.status, 0) + 1
            return counter
