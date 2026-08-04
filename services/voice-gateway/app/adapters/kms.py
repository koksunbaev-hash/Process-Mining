"""Adapter that sends recognized text commands to the KMS command API."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
import uuid
from typing import Any

from app.config import Settings
from app.schemas import VoiceCommandEvent

logger = logging.getLogger(__name__)


class KmsAdapterError(RuntimeError):
    """KMS did not accept the command."""


def forward_to_kms(event: VoiceCommandEvent, settings: Settings) -> dict[str, Any]:
    if not settings.kms_enabled:
        logger.info("KMS adapter skipped: VOICE_GATEWAY_KMS_COMMAND_URL or token is empty")
        return {"status": "skipped", "reason": "kms_not_configured"}

    payload = {
        "text": event.text,
        "client_request_id": event.request_id or f"ovos-{uuid.uuid4()}",
        "source": event.source,
        "confidence": event.confidence,
        "device_id": event.device_id,
        "intent": event.intent,
        "metadata": event.metadata,
    }
    request = urllib.request.Request(
        settings.kms_command_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.kms_api_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.http_timeout_seconds) as response:
            body = response.read().decode("utf-8") or "{}"
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise KmsAdapterError(f"KMS rejected voice event: HTTP {exc.code} {body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise KmsAdapterError(f"KMS voice event forwarding failed: {exc}") from exc
