"""Распознавание уходит в аналитику по HTTP — проверяем именно этот контракт.

Раньше модуль грузил свою модель, и тестировать было нечего: единственная
интересная строка была вызовом faster-whisper. Теперь это сетевой клиент, и
важно, как он делит ошибки: «сервис приляжет и вернётся» против «этот запрос
неверен и будет неверен всегда». Телефон на первом должен повторить, на втором
— показать человеку сообщение и остановиться.
"""

from __future__ import annotations

import io
import json
import urllib.error
from dataclasses import replace

import pytest

from app.config import load_settings
from app.services.transcription_service import (
    TranscriptionError,
    TranscriptionUnavailableError,
    transcribe_audio,
)


@pytest.fixture
def configured():
    return replace(
        load_settings(),
        transcribe_url="http://analytics.invalid/api/transcriptions/sync",
        transcribe_token="test-key",
        transcribe_timeout_seconds=5,
    )


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "voice.m4a"
    path.write_bytes(b"not really audio, but not empty either")
    return path


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _answering(payload: dict, captured: dict | None = None):
    def urlopen(request, timeout=None):
        if captured is not None:
            captured["url"] = request.full_url
            captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
            captured["body"] = request.data
            captured["timeout"] = timeout
        return _Response(json.dumps(payload).encode("utf-8"))

    return urlopen


def test_returns_the_recognised_text(monkeypatch, configured, audio):
    captured: dict = {}
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _answering({"status": "ok", "text": "партия B-154 закончила замес"}, captured),
    )

    assert transcribe_audio(audio, configured) == "партия B-154 закончила замес"
    assert captured["url"] == configured.transcribe_url
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["timeout"] == 5
    # The file has to actually be in the body, or the service transcribes silence.
    assert b"not really audio" in captured["body"]
    assert b'name="audio_file"' in captured["body"]


def test_accepts_the_transcript_field_too(monkeypatch, configured, audio):
    """The analytics service answers with both keys; either one is the answer."""
    monkeypatch.setattr("urllib.request.urlopen", _answering({"transcript": "готово"}))
    assert transcribe_audio(audio, configured) == "готово"


def test_unconfigured_is_unavailable_not_a_bad_request(configured, audio):
    with pytest.raises(TranscriptionUnavailableError):
        transcribe_audio(audio, replace(configured, transcribe_url=""))
    with pytest.raises(TranscriptionUnavailableError):
        transcribe_audio(audio, replace(configured, transcribe_token=""))


def test_empty_file_never_reaches_the_network(monkeypatch, configured, tmp_path):
    def explode(*_args, **_kwargs):
        raise AssertionError("empty audio must not be sent anywhere")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    empty = tmp_path / "silence.m4a"
    empty.write_bytes(b"")

    with pytest.raises(TranscriptionError):
        transcribe_audio(empty, configured)


def test_missing_file_never_reaches_the_network(configured, tmp_path):
    with pytest.raises(TranscriptionError):
        transcribe_audio(tmp_path / "nothing-here.m4a", configured)


def test_server_error_is_retryable(monkeypatch, configured, audio):
    def urlopen(*_args, **_kwargs):
        raise urllib.error.HTTPError("u", 503, "Service Unavailable", {}, io.BytesIO(b"model down"))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(TranscriptionUnavailableError):
        transcribe_audio(audio, configured)


def test_client_error_is_not_retryable(monkeypatch, configured, audio):
    """415 means this recording is wrong; repeating it changes nothing."""

    def urlopen(*_args, **_kwargs):
        raise urllib.error.HTTPError("u", 415, "Unsupported", {}, io.BytesIO(b"bad format"))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(TranscriptionError):
        transcribe_audio(audio, configured)


def test_unreachable_service_is_unavailable(monkeypatch, configured, audio):
    def urlopen(*_args, **_kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(TranscriptionUnavailableError):
        transcribe_audio(audio, configured)


def test_empty_answer_is_an_error(monkeypatch, configured, audio):
    """Silence recognised as nothing must not become an empty command."""
    monkeypatch.setattr("urllib.request.urlopen", _answering({"status": "ok", "text": "   "}))
    with pytest.raises(TranscriptionError):
        transcribe_audio(audio, configured)


def test_garbage_answer_is_an_error(monkeypatch, configured, audio):
    def urlopen(*_args, **_kwargs):
        return _Response(b"<html>not json</html>")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(TranscriptionError):
        transcribe_audio(audio, configured)
