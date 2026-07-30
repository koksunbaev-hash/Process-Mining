from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.core.rendering import graphviz_available
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=HealthResponse, summary="Liveness probe")
async def live(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.version,
        environment=settings.environment,
        time=datetime.now(UTC),
    )


@router.get("/health/ready", response_model=HealthResponse, summary="Readiness probe")
async def ready(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    storage = request.app.state.repository.health()
    checks = {
        "storage": storage,
        "graphviz": {"ok": graphviz_available()},
        "cache": request.app.state.cache.stats(),
        "jobs": request.app.state.job_manager.stats(),
        "voice_enabled": settings.voice_enabled,
        "auth_enabled": settings.auth_enabled,
        "mapping_profiles": [p.id for p in request.app.state.mappings.list()],
    }
    healthy = bool(storage.get("ok"))
    return HealthResponse(
        status="ok" if healthy else "degraded",
        service=settings.app_name,
        version=settings.version,
        environment=settings.environment,
        checks=checks,
        time=datetime.now(UTC),
    )
