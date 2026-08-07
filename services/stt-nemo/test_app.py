"""Контракт сервиса — то единственное, что о нём знают остальные.

Модель подменена: проверяется форма ответа, а не качество распознавания.
Качество меряется на записях из цеха, а не в юнит-тестах.

Важнее всего здесь два теста: ответ должен быть голой строкой (так отвечал
сервер OVOS, и на это рассчитывает разбор в аналитике), а сбой модели должен
превращаться в 500, а не в зависшее соединение — телефон на том конце ждёт.
"""

from __future__ import annotations

import io
import wave

import pytest
from fastapi.testclient import TestClient

import app as service


def wav_bytes(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


class FakeModel:
    def __init__(self, answer=None, error=None):
        self.answer = answer
        self.error = error
        self.calls = []

    def transcribe(self, paths, **kwargs):
        if self.error:
            raise self.error
        self.calls.append(paths)
        return self.answer


@pytest.fixture
def client(monkeypatch):
    # Ни весов, ни загрузки: сервис поднимается с уже "готовой" моделью.
    monkeypatch.setattr(service, "_load", lambda: service._model)
    monkeypatch.setenv("NEMO_PRELOAD", "false")
    with TestClient(service.app) as test_client:
        yield test_client


def test_health_answers_before_the_model_is_loaded(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["model"]


def test_the_answer_is_a_bare_string(client, monkeypatch):
    """Так отвечал сервер OVOS. Отвечать иначе - значит сломать вызывающих."""
    monkeypatch.setattr(service, "_model", FakeModel(answer=["үш жүз қырық бір на расстойку"]))

    response = client.post("/stt?lang=kk", content=wav_bytes(), headers={"Content-Type": "audio/wav"})

    assert response.status_code == 200
    assert response.text == "үш жүз қырық бір на расстойку"


def test_a_hypothesis_object_is_unwrapped(client, monkeypatch):
    class Hypothesis:
        text = "  341 печка  "

    monkeypatch.setattr(service, "_model", FakeModel(answer=[Hypothesis()]))
    assert client.post("/stt", content=wav_bytes()).text == "341 печка"


def test_a_hybrid_model_answers_with_a_pair(client, monkeypatch):
    """RNN-T и CTC сразу; берём первый - он точнее."""
    monkeypatch.setattr(service, "_model", FakeModel(answer=(["с rnnt"], ["с ctc"])))
    assert client.post("/stt", content=wav_bytes()).text == "с rnnt"


def test_language_is_accepted_and_ignored(client, monkeypatch):
    """Модель двуязычная и решает сама, но параметр шлют все вызывающие."""
    monkeypatch.setattr(service, "_model", FakeModel(answer=["текст"]))
    for query in ("", "?lang=kk", "?lang=ru-ru", "?lang=nonsense"):
        assert client.post(f"/stt{query}", content=wav_bytes()).status_code == 200


def test_empty_body_is_rejected(client):
    assert client.post("/stt", content=b"").status_code == 400


def test_oversized_audio_is_rejected(client, monkeypatch):
    monkeypatch.setattr(service, "MAX_BYTES", 1024)
    assert client.post("/stt", content=b"x" * 2048).status_code == 413


def test_a_failing_model_becomes_a_500_not_a_hang(client, monkeypatch):
    monkeypatch.setattr(service, "_model", FakeModel(error=RuntimeError("decoder exploded")))
    response = client.post("/stt", content=wav_bytes())
    assert response.status_code == 500
    assert "decoder exploded" in response.json()["error"]


def test_silence_may_come_back_empty(client, monkeypatch):
    """И это правильный ответ.

    Whisper на тишине сочинял «Редактор субтитров А.Олзоева» - фразу, которую
    разбор команд честно пытался исполнить. Пустая строка такого не делает.
    """
    monkeypatch.setattr(service, "_model", FakeModel(answer=[""]))
    response = client.post("/stt", content=wav_bytes())
    assert response.status_code == 200
    assert response.text == ""
