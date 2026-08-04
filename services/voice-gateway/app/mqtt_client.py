"""MQTT subscriber for OVOS recognized text events."""

from __future__ import annotations

import json
import logging
from typing import Any

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from app.config import Settings, settings
from app.router import route_voice_event
from app.schemas import VoiceCommandEvent

logger = logging.getLogger(__name__)


class VoiceMqttBridge:
    def __init__(self, config: Settings = settings) -> None:
        self.config = config
        self.client: mqtt.Client | None = None

    def start(self) -> bool:
        if not self.config.mqtt_enabled:
            logger.info("MQTT bridge disabled: VOICE_GATEWAY_MQTT_HOST is empty")
            return False

        client = mqtt.Client(client_id=self.config.mqtt_client_id)
        if self.config.mqtt_username:
            client.username_pw_set(self.config.mqtt_username, self.config.mqtt_password or None)
        if self.config.mqtt_tls:
            client.tls_set()

        client.on_connect = self._on_connect
        client.on_message = self._on_message
        try:
            client.connect(self.config.mqtt_host, self.config.mqtt_port, keepalive=30)
        except OSError as exc:
            logger.warning("MQTT bridge disabled: cannot connect to %s:%s: %s", self.config.mqtt_host, self.config.mqtt_port, exc)
            return False

        client.loop_start()
        self.client = client
        logger.info("MQTT bridge started topic=%s host=%s", self.config.mqtt_topic, self.config.mqtt_host)
        return True

    def stop(self) -> None:
        if not self.client:
            return
        self.client.loop_stop()
        self.client.disconnect()
        self.client = None
        logger.info("MQTT bridge stopped")

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        del userdata, flags, properties
        if reason_code == 0 or str(reason_code).lower() == "success":
            client.subscribe(self.config.mqtt_topic)
            logger.info("MQTT connected, subscribed to %s", self.config.mqtt_topic)
        else:
            logger.warning("MQTT connection failed with code=%s", reason_code)

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        del client, userdata
        try:
            raw = message.payload.decode("utf-8")
            event = VoiceCommandEvent(**json.loads(raw))
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Dropped invalid MQTT voice event on %s: %s", message.topic, exc)
            return
        result = route_voice_event(event, self.config)
        logger.info("MQTT voice event routed status=%s project=%s", result.status, result.project)
