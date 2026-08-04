"""Правила приёма и выдачи сообщений.

Слой не знает про FastAPI: валидация выражена исключениями, которые HTTP-слой
переводит в коды ответов. Это позволяет тестировать логику без TestClient.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.database.models import SpeechMessage

logger = logging.getLogger(__name__)

STATUS_RECEIVED = "received"


class SpeechValidationError(ValueError):
    """Текст не прошёл проверку. HTTP-слой отвечает 400."""


def normalize_text(raw: str, config: Settings = settings) -> str:
    """Обрезает пробелы и проверяет длину.

    Пустая строка и строка из одних пробелов равнозначны: сохранять нечего.
    """
    text = raw.strip()
    if not text:
        raise SpeechValidationError("empty text")
    if len(text) > config.max_text_length:
        raise SpeechValidationError(
            f"text too long: {len(text)} > {config.max_text_length}"
        )
    return text


def save_message(
    session: Session,
    raw_text: str,
    config: Settings = settings,
) -> SpeechMessage:
    """Проверяет текст и сохраняет реплику. Возвращает созданную запись."""
    text = normalize_text(raw_text, config)

    message = SpeechMessage(text=text, status=STATUS_RECEIVED)
    session.add(message)
    session.commit()
    session.refresh(message)

    # В лог идёт только длина: сам текст — пользовательские данные.
    logger.info(
        "Сообщение сохранено id=%s text_length=%s status=%s",
        message.id,
        len(text),
        message.status,
    )
    return message


def recent_messages(
    session: Session,
    limit: int | None = None,
    config: Settings = settings,
) -> Sequence[SpeechMessage]:
    """Последние сообщения, новые сверху."""
    effective_limit = config.history_limit if limit is None else limit
    effective_limit = max(1, min(effective_limit, config.history_limit))

    statement = (
        select(SpeechMessage)
        .order_by(SpeechMessage.created_at.desc(), SpeechMessage.id.desc())
        .limit(effective_limit)
    )
    return session.execute(statement).scalars().all()


def count_messages(session: Session) -> int:
    """Число сохранённых сообщений — используется в health-проверках и тестах."""
    return session.query(SpeechMessage).count()
