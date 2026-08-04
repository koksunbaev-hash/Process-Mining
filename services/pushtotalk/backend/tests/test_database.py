"""Тесты хранилища: автосоздание базы и сохранение записей."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.database.database import create_db_engine, init_db
from app.database.models import SpeechMessage
from app.services import speech_service


def test_database_file_is_created_on_first_run(settings, isolated_db_path: Path) -> None:
    assert not isolated_db_path.exists()

    engine = create_db_engine(settings)
    init_db(engine, settings)

    assert isolated_db_path.exists()
    engine.dispose()


def test_parent_directory_is_created(settings) -> None:
    assert not settings.data_dir.exists()

    engine = create_db_engine(settings)
    init_db(engine, settings)

    assert settings.data_dir.exists()
    engine.dispose()


def test_schema_contains_expected_columns(db_engine) -> None:
    columns = {column["name"] for column in inspect(db_engine).get_columns("speech_messages")}

    assert columns == {"id", "text", "created_at", "status"}


def test_init_db_is_idempotent(settings) -> None:
    engine = create_db_engine(settings)
    init_db(engine, settings)
    init_db(engine, settings)

    assert "speech_messages" in inspect(engine).get_table_names()
    engine.dispose()


def test_message_is_persisted(db_session) -> None:
    speech_service.save_message(db_session, "hello")

    stored = db_session.query(SpeechMessage).all()

    assert len(stored) == 1
    assert stored[0].text == "hello"
    assert stored[0].status == "received"
    assert stored[0].created_at is not None


def test_message_survives_new_session(db_engine) -> None:
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)

    with factory() as writer:
        speech_service.save_message(writer, "persisted text")

    with factory() as reader:
        assert reader.query(SpeechMessage).one().text == "persisted text"


def test_ids_increment(db_session) -> None:
    first = speech_service.save_message(db_session, "first")
    second = speech_service.save_message(db_session, "second")

    assert second.id > first.id
