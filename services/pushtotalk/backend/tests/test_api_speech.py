"""Тесты POST /api/speech."""

from __future__ import annotations


def test_valid_text_returns_ok(client) -> None:
    response = client.post("/api/speech", json={"text": "hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["id"], int)
    assert body["id"] > 0


def test_valid_text_is_forwarded_to_kms(client, monkeypatch) -> None:
    import app.api.speech as speech_api

    calls = []

    def fake_forward(text, **kwargs):
        calls.append((text, kwargs))
        return {"status": "ok", "command_id": 15}

    monkeypatch.setattr(speech_api, "forward_text_command", fake_forward)

    response = client.post("/api/speech", json={"text": "Партия DEMO-B-0012 закончила замес"})

    assert response.status_code == 200
    assert calls == [("Партия DEMO-B-0012 закончила замес", {"client_request_id": f"speech-{response.json()['id']}"})]


def test_kms_forward_error_does_not_break_speech_save(client, monkeypatch) -> None:
    import app.api.speech as speech_api
    from app.services.kms_client import KmsForwardError

    def fake_forward(text, **kwargs):
        raise KmsForwardError("down")

    monkeypatch.setattr(speech_api, "forward_text_command", fake_forward)

    response = client.post("/api/speech", json={"text": "Партия DEMO-B-0012 закончила замес"})

    assert response.status_code == 200
    assert client.get("/api/messages").json()[0]["text"] == "Партия DEMO-B-0012 закончила замес"


def test_transcribed_text_is_forwarded_to_kms(client, monkeypatch, tmp_path) -> None:
    import app.api.speech as speech_api

    calls = []
    monkeypatch.setattr(speech_api, "transcribe_audio", lambda path: "Партия DEMO-B-0012 закончила замес")
    monkeypatch.setattr(
        speech_api,
        "forward_text_command",
        lambda text, **kwargs: calls.append((text, kwargs)) or {"status": "ok"},
    )

    audio_path = tmp_path / "voice.m4a"
    audio_path.write_bytes(b"audio")
    with audio_path.open("rb") as audio:
        response = client.post("/api/speech/transcribe", files={"file": ("voice.m4a", audio, "audio/mp4")})

    assert response.status_code == 200
    assert response.json()["text"] == "Партия DEMO-B-0012 закончила замес"
    assert calls == [("Партия DEMO-B-0012 закончила замес", {"source": "pushtotalk-whisper"})]


def test_cyrillic_text_is_accepted(client) -> None:
    response = client.post("/api/speech", json={"text": "Привет сервер"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    stored = client.get("/api/messages").json()
    assert stored[0]["text"] == "Привет сервер"


def test_empty_text_returns_400(client) -> None:
    response = client.post("/api/speech", json={"text": ""})

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "empty text"


def test_whitespace_only_text_returns_400(client) -> None:
    response = client.post("/api/speech", json={"text": "   \n\t "})

    assert response.status_code == 400
    assert response.json()["message"] == "empty text"


def test_rejected_text_is_not_stored(client) -> None:
    client.post("/api/speech", json={"text": ""})

    assert client.get("/api/messages").json() == []


def test_missing_text_field_returns_422(client) -> None:
    response = client.post("/api/speech", json={})

    assert response.status_code == 422
    assert response.json()["status"] == "error"


def test_wrong_text_type_returns_422(client) -> None:
    response = client.post("/api/speech", json={"text": 42})

    assert response.status_code == 422


def test_malformed_json_returns_422(client) -> None:
    response = client.post(
        "/api/speech",
        content=b"{not valid json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


def test_very_long_text_is_rejected_without_crash(client) -> None:
    response = client.post("/api/speech", json={"text": "a" * 50_000})

    assert response.status_code == 400
    assert "too long" in response.json()["message"]

    # Сервис остался работоспособным.
    assert client.post("/api/speech", json={"text": "still alive"}).status_code == 200


def test_text_at_length_limit_is_accepted(client, settings) -> None:
    response = client.post("/api/speech", json={"text": "a" * settings.max_text_length})

    assert response.status_code == 200


def test_text_is_trimmed_before_saving(client) -> None:
    client.post("/api/speech", json={"text": "  привет мир  "})

    assert client.get("/api/messages").json()[0]["text"] == "привет мир"


def test_health_endpoint(client) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
