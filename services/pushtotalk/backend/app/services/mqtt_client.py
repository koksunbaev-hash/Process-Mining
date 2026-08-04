"""Publish recognized voice text to the shared MQTT command bus."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import paho.mqtt.client as mqtt

from app.config import Settings, settings

logger = logging.getLogger(__name__)


class MqttPublishError(RuntimeError):
    """MQTT broker did not accept the message."""


def is_configured(config: Settings = settings) -> bool:
    return config.mqtt_enabled


def publish_text_command(
    text: str,
    *,
    client_request_id: str | None = None,
    source: str = "pushtotalk",
    confidence: float | None = None,
    config: Settings = settings,
) -> dict[str, Any]:
    if not is_configured(config):
        logger.info("MQTT publish skipped: PTT_MQTT_HOST is empty")
        return {"status": "skipped", "reason": "mqtt_not_configured"}

    request_id = client_request_id or f"ptt-{uuid.uuid4()}"
    payload = {
        "project": config.mqtt_project,
        "source": source,
        "request_id": request_id,
        "device_id": config.mqtt_client_id,
        "text": text,
        "confidence": confidence,
        "metadata": {
            "producer": "pushtotalk-backend",
        },
    }

    client = mqtt.Client(client_id=f"{config.mqtt_client_id}-{uuid.uuid4().hex[:8]}")
    if config.mqtt_username:
        client.username_pw_set(config.mqtt_username, config.mqtt_password or None)
    if config.mqtt_tls:
        client.tls_set()

    try:
        client.connect(config.mqtt_host, config.mqtt_port, keepalive=30)
        client.loop_start()
        info = client.publish(
            config.mqtt_topic,
            json.dumps(payload, ensure_ascii=False),
            qos=1,
        )
        info.wait_for_publish(timeout=config.mqtt_timeout_seconds)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise MqttPublishError(f"MQTT publish failed rc={info.rc}")
    except (OSError, TimeoutError, ValueError, MqttPublishError) as exc:
        raise MqttPublishError(f"MQTT command publish failed: {exc}") from exc
    finally:
        client.loop_stop()
        client.disconnect()

    logger.info("Published PushToTalk text to MQTT topic=%s request_id=%s", config.mqtt_topic, request_id)
    return {"status": "ok", "request_id": request_id, "topic": config.mqtt_topic}
