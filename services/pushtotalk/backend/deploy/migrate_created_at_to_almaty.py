#!/usr/bin/env python3
"""Разовый перевод накопленных `created_at` из UTC во время Алматы (UTC+5).

До этой правки сервис писал в базу UTC, поэтому старые строки отстают на пять
часов. Скрипт сдвигает их ровно один раз: факт применения отмечается в таблице
`applied_migrations`, поэтому повторный запуск — в том числе из `install.sh` при
каждом деплое — уже ничего не меняет.

    python3 deploy/migrate_created_at_to_almaty.py [/opt/push-to-talk/data/speech.db]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

MIGRATION_NAME = "created_at_utc_to_almaty"
DEFAULT_DB = Path("/opt/push-to-talk/data/speech.db")
SHIFT = "+5 hours"

ALREADY_APPLIED = -1


def migrate(db_path: Path) -> int:
    """Сдвигает `created_at` на +5 часов.

    Возвращает число изменённых строк или `ALREADY_APPLIED`, если миграция
    уже отмечена как выполненная. Для базы без таблицы `speech_messages`
    (свежая установка, где время уже пишется местное) миграция отмечается
    выполненной без изменений — чтобы позже не сдвинуть корректные строки.
    """
    connection = sqlite3.connect(db_path)
    try:
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS applied_migrations ("
                "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = connection.execute(
                "SELECT 1 FROM applied_migrations WHERE name = ?", (MIGRATION_NAME,)
            ).fetchone()
            if applied:
                return ALREADY_APPLIED

            table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'speech_messages'"
            ).fetchone()

            updated = 0
            if table_exists:
                cursor = connection.execute(
                    "UPDATE speech_messages SET created_at = datetime(created_at, ?)",
                    (SHIFT,),
                )
                updated = cursor.rowcount

            connection.execute(
                "INSERT INTO applied_migrations (name, applied_at) VALUES (?, datetime('now', ?))",
                (MIGRATION_NAME, SHIFT),
            )
            return updated
    finally:
        connection.close()


def main(argv: list[str]) -> int:
    db_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_DB

    if not db_path.exists():
        print(f"База {db_path} не найдена — миграция не нужна")
        return 0

    result = migrate(db_path)
    if result == ALREADY_APPLIED:
        print(f"Миграция {MIGRATION_NAME} уже применена — пропущено")
    else:
        print(f"Миграция {MIGRATION_NAME}: сдвинуто строк — {result}")
    return 0


if __name__ == "__main__":  # pragma: no cover - точка входа
    raise SystemExit(main(sys.argv))
