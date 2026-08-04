"""FastAPI entry point for the reusable voice command gateway."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException

from app import __version__
from app.config import Settings, settings
from app.mqtt_client import VoiceMqttBridge
from app.router import route_voice_event
from app.schemas import RouteResult, VoiceCommandEvent

bridge = VoiceMqttBridge(settings)


def require_gateway_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.api_token:
        return
    expected = f"Bearer {settings.api_token}"
    if authorization != expected:
        raise HTTPException(status_code=403, detail="Invalid voice gateway token.")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    bridge.start()
    yield
    bridge.stop()


app = FastAPI(
    title="Voice Gateway",
    version=__version__,
    description="Reusable MQTT/OVOS bridge that routes recognized text commands to project adapters.",
    lifespan=lifespan,
)


@app.get("/health", tags=["service"])
@app.get("/api/health", tags=["service"])
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "version": __version__,
        "project": settings.project,
        "mqtt_enabled": settings.mqtt_enabled,
        "mqtt_topic": settings.mqtt_topic,
        "kms_enabled": settings.kms_enabled,
    }


@app.post("/api/voice-events/", response_model=RouteResult, tags=["voice"])
def receive_voice_event(
    event: VoiceCommandEvent,
    _: None = Depends(require_gateway_token),
) -> RouteResult:
    return route_voice_event(event)
