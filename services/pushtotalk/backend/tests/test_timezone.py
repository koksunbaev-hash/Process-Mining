"""Тесты часового пояса: база, ответ API и разовая миграция старых строк."""

from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from app.services import speech_service
from app.timeutils import ALMATY_TZ, almaty_now, almaty_timetuple, as_almaty

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "deploy" / "migrate_created_at_to_almaty.py"

TOLERANCE = timedelta(minutes=1)


@pytest.fixture()
def migration():
    """Скрипт миграции лежит вне пакета `app`, поэтому грузим его по пути."""
    spec = importlib.util.spec_from_file_location("ptt_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_almaty_now_is_five_hours_ahead_of_utc() -> None:
    naive_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    assert abs((almaty_now() - naive_utc) - timedelta(hours=5)) < TOLERANCE


def test_as_almaty_marks_naive_and_converts_aware() -> None:
    naive = datetime(2026, 7, 28, 20, 30)
    aware_utc = datetime(2026, 7, 28, 15, 30, tzinfo=timezone.utc)

    assert as_almaty(naive).isoformat() == "2026-07-28T20:30:00+05:00"
    assert as_almaty(aware_utc).isoformat() == "2026-07-28T20:30:00+05:00"


def test_log_timestamps_use_almaty_time() -> None:
    moment = datetime(2026, 7, 28, 15, 30, tzinfo=timezone.utc).timestamp()

    stamp = almaty_timetuple(moment)

    assert (stamp.tm_hour, stamp.tm_min) == (20, 30)


def test_saved_message_stores_almaty_time(db_session) -> None:
    message = speech_service.save_message(db_session, "привет")

    assert abs(message.created_at - almaty_now()) < TOLERANCE


def test_server_default_stores_almaty_time(db_engine) -> None:
    """Вставка в обход ORM опирается на DDL-умолчание, а не на Python."""
    with db_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO speech_messages (text, status) VALUES ('raw', 'received')")
        )
        stored = connection.execute(text("SELECT created_at FROM speech_messages")).scalar_one()

    assert abs(datetime.fromisoformat(stored) - almaty_now()) < TOLERANCE


def test_api_returns_created_at_with_almaty_offset(client) -> None:
    client.post("/api/speech", json={"text": "привет"})

    body = client.get("/api/messages").json()
    created_at = datetime.fromisoformat(body[0]["created_at"])

    assert created_at.utcoffset() == timedelta(hours=5)
    assert abs(created_at - datetime.now(ALMATY_TZ)) < TOLERANCE


def test_migration_shifts_old_rows_by_five_hours(db_engine, settings, migration) -> None:
    db_path = settings.database_path
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO speech_messages (text, created_at, status) "
            "VALUES ('старая запись', '2026-07-28 10:00:00', 'received')"
        )

    assert migration.migrate(db_path) == 1

    with sqlite3.connect(db_path) as connection:
        stored = connection.execute("SELECT created_at FROM speech_messages").fetchone()[0]

    assert stored == "2026-07-28 15:00:00"


def test_migration_is_idempotent(db_engine, settings, migration) -> None:
    db_path = settings.database_path
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO speech_messages (text, created_at, status) "
            "VALUES ('старая запись', '2026-07-28 10:00:00', 'received')"
        )

    migration.migrate(db_path)
    assert migration.migrate(db_path) == migration.ALREADY_APPLIED

    with sqlite3.connect(db_path) as connection:
        stored = connection.execute("SELECT created_at FROM speech_messages").fetchone()[0]

    assert stored == "2026-07-28 15:00:00"


def test_migration_marks_fresh_database_without_touching_future_rows(tmp_path, migration) -> None:
    """Свежая база уже пишет местное время — сдвигать её нельзя никогда."""
    db_path = tmp_path / "empty.db"
    sqlite3.connect(db_path).close()

    assert migration.migrate(db_path) == 0
    assert migration.migrate(db_path) == migration.ALREADY_APPLIED


def test_migration_main_skips_missing_database(tmp_path, migration, capsys) -> None:
    assert migration.main(["migrate", str(tmp_path / "absent.db")]) == 0
    assert "не найдена" in capsys.readouterr().out


def test_migration_main_reports_result(tmp_path, migration, capsys) -> None:
    db_path = tmp_path / "speech.db"
    sqlite3.connect(db_path).close()

    assert migration.main(["migrate", str(db_path)]) == 0
    assert "сдвинуто строк" in capsys.readouterr().out

    assert migration.main(["migrate", str(db_path)]) == 0
    assert "уже применена" in capsys.readouterr().out
