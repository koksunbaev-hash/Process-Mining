"""Environment driven settings for the voice gateway."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_token: str
    project: str
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    mqtt_tls: bool
    mqtt_client_id: str
    mqtt_topic: str
    kms_command_url: str
    kms_api_token: str
    http_timeout_seconds: int

    @property
    def mqtt_enabled(self) -> bool:
        return bool(self.mqtt_host)

    @property
    def kms_enabled(self) -> bool:
        return bool(self.kms_command_url and self.kms_api_token)


def load_settings() -> Settings:
    return Settings(
        api_token=os.getenv("VOICE_GATEWAY_API_TOKEN", ""),
        project=os.getenv("VOICE_GATEWAY_PROJECT", "kms"),
        mqtt_host=os.getenv("VOICE_GATEWAY_MQTT_HOST", ""),
        mqtt_port=int(os.getenv("VOICE_GATEWAY_MQTT_PORT", "1883")),
        mqtt_username=os.getenv("VOICE_GATEWAY_MQTT_USERNAME", ""),
        mqtt_password=os.getenv("VOICE_GATEWAY_MQTT_PASSWORD", ""),
        mqtt_tls=_bool("VOICE_GATEWAY_MQTT_TLS", False),
        mqtt_client_id=os.getenv("VOICE_GATEWAY_CLIENT_ID", "voice-gateway"),
        mqtt_topic=os.getenv("VOICE_GATEWAY_SUBSCRIBE_TOPIC", "voice/commands/recognized"),
        kms_command_url=os.getenv("VOICE_GATEWAY_KMS_COMMAND_URL", ""),
        kms_api_token=os.getenv("VOICE_GATEWAY_KMS_API_TOKEN", ""),
        http_timeout_seconds=int(os.getenv("VOICE_GATEWAY_HTTP_TIMEOUT_SECONDS", "10")),
    )


settings = load_settings()
