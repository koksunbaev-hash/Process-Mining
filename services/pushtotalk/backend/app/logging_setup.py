"""Настройка логирования.

Пишем в файл и в stdout. В лог попадают метод, путь, длина текста и статус —
но никогда сам текст, токены или заголовки авторизации.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.config import Settings, settings
from app.timeutils import almaty_timetuple

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5


def configure_logging(config: Settings = settings) -> logging.Logger:
    """Настраивает корневой логгер.

    Повторный вызов не дублирует обработчики: свои снимаются и создаются заново,
    поэтому смена каталога логов (например, в тестах) вступает в силу сразу.
    """
    config.log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(config.log_level)

    for handler in [h for h in root.handlers if getattr(h, "_ptt_handler", False)]:
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    # Метки времени в логе — по Алматы, как и `created_at` в базе:
    # на сервере с TZ=UTC они иначе расходятся на пять часов.
    formatter.converter = almaty_timetuple

    file_handler = RotatingFileHandler(
        config.log_file,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler._ptt_handler = True  # type: ignore[attr-defined]

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler._ptt_handler = True  # type: ignore[attr-defined]

    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    return root
