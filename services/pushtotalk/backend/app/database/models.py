"""ORM-модели."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy import text as sql_text  # `text` внутри класса занято колонкой
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.timeutils import SQLITE_ALMATY_NOW, almaty_now


class Base(DeclarativeBase):
    """Базовый класс всех таблиц."""


class SpeechMessage(Base):
    """Одна реплика, распознанная на устройстве и принятая сервером."""

    __tablename__ = "speech_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Время местное (Алматы, UTC+5) и в ORM-вставках, и в DDL-умолчании:
    # CURRENT_TIMESTAMP отдал бы UTC и запись «отставала» бы на пять часов.
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=almaty_now,
        server_default=sql_text(SQLITE_ALMATY_NOW),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")

    def __repr__(self) -> str:  # pragma: no cover - только для отладки
        return f"<SpeechMessage id={self.id} status={self.status!r} len={len(self.text)}>"
