"""Тесты инфраструктуры: сессии, конфигурация, обработка непредвиденных сбоев."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy.orm import sessionmaker

from app.config import Settings, load_settings
from app.database.models import SpeechMessage
from app.logging_setup import configure_logging


def test_settings_read_environment(settings: Settings, temp_env) -> None:
    assert settings.data_dir == temp_env / "data"
    assert settings.log_dir == temp_env / "logs"
    assert settings.log_file == temp_env / "logs" / "app.log"
    assert settings.database_path.name == "speech.db"


def test_database_path_is_empty_for_non_sqlite_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PTT_DATABASE_URL", "postgresql://user@host/db")

    assert load_settings().database_path.name == ""


def test_get_session_yields_and_closes(db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.database.database as database_module

    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(database_module, "SessionLocal", factory)

    generator = database_module.get_session()
    session = next(generator)
    session.add(SpeechMessage(text="from get_session", status="received"))
    session.commit()

    with pytest.raises(StopIteration):
        next(generator)

    with factory() as reader:
        assert reader.query(SpeechMessage).one().text == "from get_session"


def test_session_scope_commits(db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.database.database as database_module

    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(database_module, "SessionLocal", factory)

    with database_module.session_scope() as session:
        session.add(SpeechMessage(text="committed", status="received"))

    with factory() as reader:
        assert reader.query(SpeechMessage).one().text == "committed"


def test_session_scope_rolls_back_on_error(db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.database.database as database_module

    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(database_module, "SessionLocal", factory)

    with pytest.raises(RuntimeError):
        with database_module.session_scope() as session:
            session.add(SpeechMessage(text="rolled back", status="received"))
            raise RuntimeError("сбой в середине транзакции")

    with factory() as reader:
        assert reader.query(SpeechMessage).count() == 0


def test_logging_reconfiguration_does_not_duplicate_handlers(settings) -> None:
    configure_logging(settings)
    first = len([h for h in logging.getLogger().handlers if getattr(h, "_ptt_handler", False)])

    configure_logging(settings)
    second = len([h for h in logging.getLogger().handlers if getattr(h, "_ptt_handler", False)])

    assert first == second == 2


def test_unexpected_error_returns_500_without_crashing(settings, db_engine, monkeypatch) -> None:
    """Сбой внутри сервиса превращается в 500, а не в падение процесса."""
    from fastapi.testclient import TestClient

    import app.api.speech as speech_api
    import app.main as main_module
    from app.database.database import get_session

    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)

    def override_session():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    def explode(*_args, **_kwargs):
        raise RuntimeError("база недоступна")

    monkeypatch.setattr(speech_api, "settings", settings)
    monkeypatch.setattr(main_module, "settings", settings)
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    monkeypatch.setattr(speech_api.speech_service, "save_message", explode)

    app = main_module.app
    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/api/speech", json={"text": "hello"})

            assert response.status_code == 500
            assert response.json() == {"status": "error", "message": "internal server error"}
    finally:
        app.dependency_overrides.clear()
