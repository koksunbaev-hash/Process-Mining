"""Forward recognized text commands to the KMS site."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
import uuid

from app.config import Settings, settings

logger = logging.getLogger(__name__)


class KmsForwardError(RuntimeError):
    """KMS did not accept a recognized command."""


def is_configured(config: Settings = settings) -> bool:
    return bool(config.kms_command_url and config.kms_api_token)


def forward_text_command(
    text: str,
    *,
    client_request_id: str | None = None,
    source: str = "pushtotalk",
    config: Settings = settings,
) -> dict:
    """Send a recognized phrase to KMS without exposing the KMS token to Android."""
    if not is_configured(config):
        logger.info("KMS forwarding skipped: PTT_KMS_COMMAND_URL or PTT_KMS_API_TOKEN is empty")
        return {"status": "skipped", "reason": "not_configured"}

    payload = {
        "text": text,
        "client_request_id": client_request_id or f"ptt-{uuid.uuid4()}",
        "source": source,
    }
    request = urllib.request.Request(
        config.kms_command_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.kms_api_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.kms_timeout_seconds) as response:
            body = response.read().decode("utf-8") or "{}"
            data = json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise KmsForwardError(f"KMS rejected command: HTTP {exc.code} {body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise KmsForwardError(f"KMS command forwarding failed: {exc}") from exc

    logger.info(
        "Forwarded PushToTalk text to KMS status=%s command_id=%s",
        data.get("status"),
        data.get("command_id"),
    )
    return data
