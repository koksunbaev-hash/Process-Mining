"""Общие фикстуры.

Каждый тест получает собственную временную базу и каталог логов, поэтому
набор не зависит от порядка выполнения и не трогает боевые данные.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Переменные окружения читаются в момент импорта app.config,
# поэтому подменяем их до первого импорта приложения.
_TEST_ROOT = Path(__file__).resolve().parent


@pytest.fixture()
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Изолированные каталоги данных и логов."""
    data_dir = tmp_path / "data"
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("PTT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PTT_LOG_DIR", str(log_dir))
    monkeypatch.setenv("PTT_DATABASE_URL", f"sqlite:///{data_dir / 'speech.db'}")
    return tmp_path


@pytest.fixture()
def settings(temp_env: Path):
    """Конфигурация, указывающая на временные каталоги."""
    from app.config import load_settings

    return load_settings()


@pytest.fixture()
def db_engine(settings):
    """Engine поверх временного файла базы; таблицы создаются автоматически."""
    from app.database.database import create_db_engine, init_db

    engine = create_db_engine(settings)
    init_db(engine, settings)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine) -> Iterator:
    """Сессия SQLAlchemy для тестов сервисного слоя."""
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(settings, db_engine, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    """TestClient поверх временной базы.

    Стартовый хук приложения обезврежен: таблицы уже созданы фикстурой
    `db_engine`, а боевой engine из `app.database.database` трогать нельзя.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    import app.api.speech as speech_api
    import app.main as main_module
    from app.database.database import get_session

    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False, future=True)

    def override_session():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    # Модули читают настройки на уровне импорта — подменяем все обращения.
    monkeypatch.setattr(speech_api, "settings", settings)
    monkeypatch.setattr(main_module, "settings", settings)
    monkeypatch.setattr(main_module, "init_db", lambda: None)

    fastapi_app = main_module.app
    fastapi_app.dependency_overrides[get_session] = override_session

    with TestClient(fastapi_app) as test_client:
        yield test_client

    fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def isolated_db_path(temp_env: Path) -> Path:
    """Путь к файлу базы, которого ещё нет на диске."""
    return temp_env / "data" / "speech.db"
