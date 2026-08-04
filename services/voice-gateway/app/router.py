"""Routing voice events from reusable input channels to project adapters."""

from __future__ import annotations

import logging

from app.adapters.kms import KmsAdapterError, forward_to_kms
from app.config import Settings, settings
from app.schemas import RouteResult, VoiceCommandEvent

logger = logging.getLogger(__name__)


def route_voice_event(event: VoiceCommandEvent, config: Settings = settings) -> RouteResult:
    if event.project != config.project:
        logger.info("Skipping voice event for project=%s, gateway project=%s", event.project, config.project)
        return RouteResult(status="skipped", project=event.project, reason="project_mismatch")

    if event.project == "kms":
        try:
            response = forward_to_kms(event, config)
        except KmsAdapterError as exc:
            logger.warning("KMS adapter failed: %s", exc)
            return RouteResult(status="failed", project=event.project, reason=str(exc))
        return RouteResult(
            status=response.get("status", "ok"),
            project=event.project,
            forwarded=response.get("status") != "skipped",
            reason=response.get("reason"),
            adapter_response=response,
        )

    logger.info("No adapter registered for project=%s", event.project)
    return RouteResult(status="skipped", project=event.project, reason="unknown_project")
