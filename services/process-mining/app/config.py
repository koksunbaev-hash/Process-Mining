"""Application settings.

Everything is configured through environment variables prefixed with ``PM_``
(or a local ``.env`` file). Nothing in the codebase reads ``os.environ``
directly - always go through :func:`get_settings`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Defaults are anchored to the service directory, not to the current working
# directory. Otherwise `uvicorn` started from a parent folder - which is what
# happens in a monorepo - would look for ./config/activities.yaml next to
# wherever the shell happened to be, and silently fall back to no profiles.
SERVICE_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PM_",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Core ----
    app_name: str = "process-mining-service"
    version: str = "1.0.0"
    environment: Literal["local", "dev", "staging", "prod"] = "local"
    debug: bool = False
    api_prefix: str = "/api/v1"
    host: str = "0.0.0.0"
    port: int = 8000

    # ---- Security ----
    api_keys: str = ""
    cors_origins: str = "*"

    # ---- Limits ----
    max_upload_mb: int = 64
    max_events_per_log: int = 2_000_000
    job_ttl_seconds: int = 3600
    render_timeout_seconds: int = 60
    max_concurrent_jobs: int = 4

    # ---- Storage ----
    storage_backend: Literal["memory", "sqlite"] = "sqlite"
    sqlite_path: Path = SERVICE_ROOT / "data" / "pm.db"
    artifact_dir: Path = SERVICE_ROOT / "data" / "artifacts"

    # ---- Domain mapping ----
    mapping_config: Path = SERVICE_ROOT / "config" / "activities.yaml"
    default_mapping_profile: str = "generic"

    # ---- Voice (optional module) ----
    voice_enabled: bool = False
    whisper_model: str = "turbo"
    whisper_language: str = "ru"
    max_audio_seconds: int = 300

    # ---- Speech-to-text over HTTP ----
    # The model runs in its own container (see the `stt` service), so this one
    # stays small and a GPU can be given to speech alone.
    stt_url: str = "http://stt:8080"
    stt_language: str = "ru"
    stt_timeout_seconds: int = 120
    stt_sample_rate: int = 16000

    # Callbacks are signed with HMAC-SHA256 over the raw body; the receiver
    # rejects anything unsigned, so an empty secret disables sending.
    callback_secret: str = ""
    callback_timeout_seconds: int = 10
    callback_retries: int = 3

    # ---- Observability ----
    log_level: str = "INFO"
    log_json: bool = True

    @field_validator("api_keys", "cors_origins", mode="before")
    @classmethod
    def _coerce_csv(cls, value: object) -> str:
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return str(value or "")

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()] or ["*"]

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key_set)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


__all__ = ["Settings", "get_settings", "Field"]
