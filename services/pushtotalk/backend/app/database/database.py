"""Подключение к SQLite и управление сессиями.

База и её каталог создаются автоматически при первом запуске — отдельный шаг
инициализации не нужен ни в проде, ни в тестах.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, settings
from app.database.models import Base

logger = logging.getLogger(__name__)


def create_db_engine(config: Settings = settings) -> Engine:
    """Создаёт engine. Соединение ленивое: файл базы появится при `init_db`."""
    return create_engine(
        config.database_url,
        # SQLite по умолчанию запрещает работу соединения из другого потока,
        # а FastAPI выполняет синхронные обработчики в пуле потоков.
        connect_args={"check_same_thread": False},
        future=True,
    )


engine: Engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db(db_engine: Engine | None = None, config: Settings = settings) -> None:
    """Создаёт каталог, файл базы и таблицы.

    Идемпотентно: повторный вызов ничего не ломает, поэтому отдельный шаг
    миграции при первом запуске не нужен.
    """
    db_path = config.database_path
    if db_path.name:
        db_path.parent.mkdir(parents=True, exist_ok=True)

    target = db_engine or engine
    Base.metadata.create_all(bind=target)
    logger.info("База данных готова: %s", target.url)


def get_session() -> Iterator[Session]:
    """FastAPI-зависимость: сессия на один запрос."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Сессия для кода вне HTTP-обработчиков (скрипты, фоновые задачи)."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
