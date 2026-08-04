"""Конфигурация сервиса.

Все пути и лимиты задаются переменными окружения, чтобы один и тот же код
работал и на боевом Linux-хосте (`/opt/push-to-talk`), и на машине разработчика.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Каталог самого приложения: backend/
BASE_DIR = Path(__file__).resolve().parent.parent

# На Linux сервис живёт в /opt/push-to-talk, на других ОС этого пути нет,
# поэтому по умолчанию используется каталог рядом с кодом.
DEFAULT_ROOT = Path("/opt/push-to-talk") if os.name == "posix" else BASE_DIR


def _resolve_dir(env_name: str, default: Path) -> Path:
    raw = os.getenv(env_name)
    return Path(raw).expanduser() if raw else default


@dataclass(frozen=True)
class Settings:
    """Неизменяемый снимок конфигурации."""

    data_dir: Path
    log_dir: Path
    database_url: str
    max_text_length: int
    history_limit: int
    log_level: str
    kms_command_url: str
    kms_api_token: str
    kms_timeout_seconds: int

    @property
    def database_path(self) -> Path:
        """Путь к файлу SQLite; пустой для in-memory баз в тестах."""
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return Path()
        return Path(self.database_url[len(prefix):])

    @property
    def log_file(self) -> Path:
        return self.log_dir / "app.log"


def load_settings() -> Settings:
    """Собирает конфигурацию из окружения. Вызывается один раз при старте."""
    data_dir = _resolve_dir("PTT_DATA_DIR", DEFAULT_ROOT / "data")
    log_dir = _resolve_dir("PTT_LOG_DIR", DEFAULT_ROOT / "logs")
    database_url = os.getenv("PTT_DATABASE_URL", f"sqlite:///{data_dir / 'speech.db'}")

    return Settings(
        data_dir=data_dir,
        log_dir=log_dir,
        database_url=database_url,
        max_text_length=int(os.getenv("PTT_MAX_TEXT_LENGTH", "10000")),
        history_limit=int(os.getenv("PTT_HISTORY_LIMIT", "50")),
        log_level=os.getenv("PTT_LOG_LEVEL", "INFO").upper(),
        kms_command_url=os.getenv("PTT_KMS_COMMAND_URL", ""),
        kms_api_token=os.getenv("PTT_KMS_API_TOKEN", ""),
        kms_timeout_seconds=int(os.getenv("PTT_KMS_TIMEOUT_SECONDS", "10")),
    )


settings = load_settings()
