from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import jobs, logs, mining, profiles, voice

api_router = APIRouter()
api_router.include_router(logs.router)
api_router.include_router(mining.router)
api_router.include_router(profiles.router)
api_router.include_router(jobs.router)

voice_router = voice.router
