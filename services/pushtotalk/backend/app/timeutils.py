"""Единая точка работы со временем.

Сервис обслуживает Алматы, поэтому местное время используется везде: в базе,
в логах и в ответах API. Казахстан с 1 марта 2024 года живёт в одном поясе
UTC+5 и не переходит на летнее время, поэтому фиксированного смещения
достаточно — база `tzdata` на хосте не нужна.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

ALMATY_TZ = timezone(timedelta(hours=5), "Asia/Almaty")

# Тот же сдвиг для SQL-выражений: CURRENT_TIMESTAMP в SQLite отдаёт UTC.
SQLITE_ALMATY_NOW = "(datetime('now', '+5 hours'))"


def almaty_now() -> datetime:
    """Текущее время Алматы без tzinfo: SQLite таймзону не хранит."""
    return datetime.now(ALMATY_TZ).replace(tzinfo=None)


def as_almaty(value: datetime) -> datetime:
    """Помечает наивное значение из базы поясом Алматы (или переводит в него)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=ALMATY_TZ)
    return value.astimezone(ALMATY_TZ)


def almaty_timetuple(timestamp: float) -> time.struct_time:
    """Конвертер меток для logging: лог идёт по Алматы, а не по TZ хоста."""
    return datetime.fromtimestamp(timestamp, ALMATY_TZ).timetuple()
