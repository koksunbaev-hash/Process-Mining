"""Тесты бизнес-логики без HTTP-слоя."""

from __future__ import annotations

import pytest

from app.services.speech_service import (
    SpeechValidationError,
    count_messages,
    normalize_text,
    recent_messages,
    save_message,
)


def test_normalize_trims_whitespace(settings) -> None:
    assert normalize_text("  привет  ", settings) == "привет"


@pytest.mark.parametrize("raw", ["", "   ", "\n", "\t\r\n "])
def test_blank_text_is_rejected(settings, raw: str) -> None:
    with pytest.raises(SpeechValidationError, match="empty text"):
        normalize_text(raw, settings)


def test_too_long_text_is_rejected(settings) -> None:
    with pytest.raises(SpeechValidationError, match="too long"):
        normalize_text("a" * (settings.max_text_length + 1), settings)


def test_text_at_limit_is_accepted(settings) -> None:
    text = "a" * settings.max_text_length

    assert normalize_text(text, settings) == text


def test_save_message_returns_persisted_row(db_session, settings) -> None:
    message = save_message(db_session, "hello", settings)

    assert message.id is not None
    assert message.text == "hello"
    assert message.status == "received"


def test_save_message_rejects_blank_without_writing(db_session, settings) -> None:
    with pytest.raises(SpeechValidationError):
        save_message(db_session, "  ", settings)

    assert count_messages(db_session) == 0


def test_recent_messages_are_newest_first(db_session, settings) -> None:
    for text in ("one", "two", "three"):
        save_message(db_session, text, settings)

    assert [m.text for m in recent_messages(db_session, config=settings)] == [
        "three",
        "two",
        "one",
    ]


def test_recent_messages_respects_limit(db_session, settings) -> None:
    for text in ("one", "two", "three"):
        save_message(db_session, text, settings)

    assert len(recent_messages(db_session, limit=2, config=settings)) == 2


def test_recent_messages_caps_limit_at_history_limit(db_session, settings) -> None:
    for index in range(settings.history_limit + 5):
        save_message(db_session, f"text-{index}", settings)

    result = recent_messages(db_session, limit=1000, config=settings)

    assert len(result) == settings.history_limit


def test_recent_messages_on_empty_table(db_session, settings) -> None:
    assert recent_messages(db_session, config=settings) == []
