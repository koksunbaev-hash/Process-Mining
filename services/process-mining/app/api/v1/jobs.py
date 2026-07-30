from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, JobManagerDep
from app.schemas.mining import JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut], summary="List recent jobs")
async def list_jobs(
    jobs: JobManagerDep, _: ApiKeyDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> Any:
    return jobs.list(limit)


@router.get("/{job_id}", response_model=JobOut, summary="Poll a job")
async def get_job(job_id: str, jobs: JobManagerDep, _: ApiKeyDep) -> Any:
    return jobs.get(job_id)
