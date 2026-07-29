"""FastAPI dependencies: auth + wiring of singletons."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, Request

from app.config import Settings, get_settings
from app.errors import AuthError
from app.jobs.manager import JobManager
from app.services.log_service import LogService
from app.services.mining_service import MiningService

def get_app_settings(request: Request) -> Settings:
    """The settings this app was actually built with.

    Resolving through ``get_settings()`` instead would read the process-wide
    ``.env`` and quietly ignore the Settings passed to ``create_app`` - which
    meant a service configured with one key set authenticated against another.
    """
    return getattr(request.app.state, "settings", None) or get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


async def require_api_key(
    settings: SettingsDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Accepts ``X-API-Key: <key>`` or ``Authorization: Bearer <key>``."""
    if not settings.auth_enabled:
        return "anonymous"

    presented = x_api_key
    if not presented and authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()

    if not presented:
        raise AuthError("Missing API key. Send X-API-Key or Authorization: Bearer <key>.")

    for known in settings.api_key_set:
        if secrets.compare_digest(presented, known):
            return known
    raise AuthError("Invalid API key.")


ApiKeyDep = Annotated[str, Depends(require_api_key)]


def get_log_service(request: Request) -> LogService:
    return request.app.state.log_service


def get_mining_service(request: Request) -> MiningService:
    return request.app.state.mining_service


def get_job_manager(request: Request) -> JobManager:
    return request.app.state.job_manager


LogServiceDep = Annotated[LogService, Depends(get_log_service)]
MiningServiceDep = Annotated[MiningService, Depends(get_mining_service)]
JobManagerDep = Annotated[JobManager, Depends(get_job_manager)]
