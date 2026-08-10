"""Tests for POST /api/speech and speech command dispatch."""

from __future__ import annotations


def test_valid_text_returns_ok(client) -> None:
    response = client.post("/api/speech", json={"text": "hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["id"], int)
    assert body["id"] > 0


def test_valid_text_is_dispatched_to_kms_when_mqtt_is_not_configured(client, monkeypatch) -> None:
    import app.api.speech as speech_api

    calls = []

    def fake_forward(text, **kwargs):
        calls.append((text, kwargs))
        return {"status": "ok", "command_id": 15}

    monkeypatch.setattr(speech_api, "forward_text_command", fake_forward)

    response = client.post("/api/speech", json={"text": "Batch DEMO-B-0012 finished mixing"})

    assert response.status_code == 200
    assert calls == [
        (
            "Batch DEMO-B-0012 finished mixing",
            {"client_request_id": f"speech-{response.json()['id']}", "source": "pushtotalk"},
        )
    ]


def test_kms_forward_error_returns_502_but_keeps_local_history(client, monkeypatch) -> None:
    import app.api.speech as speech_api
    from app.services.kms_client import KmsForwardError

    def fake_forward(text, **kwargs):
        raise KmsForwardError("down")

    monkeypatch.setattr(speech_api, "forward_text_command", fake_forward)

    response = client.post("/api/speech", json={"text": "Batch DEMO-B-0012 finished mixing"})

    assert response.status_code == 502
    assert response.json()["message"] == "KMS не принял текст. Повторите отправку."
    assert client.get("/api/messages").json()[0]["text"] == "Batch DEMO-B-0012 finished mixing"


def test_mqtt_publish_keeps_direct_kms_result_for_android_feedback(client, monkeypatch) -> None:
    import app.api.speech as speech_api

    mqtt_calls = []
    kms_calls = []
    monkeypatch.setattr(
        speech_api,
        "publish_text_command",
        lambda text, **kwargs: mqtt_calls.append((text, kwargs)) or {"status": "ok"},
    )
    monkeypatch.setattr(
        speech_api,
        "forward_text_command",
        lambda text, **kwargs: kms_calls.append((text, kwargs))
        or {"status": "ok", "executed": False, "command_status": "needs_review", "reason": "Не понял этап."},
    )

    response = client.post("/api/speech", json={"text": "DEMO-B-0012 ready"})

    assert response.status_code == 200
    assert mqtt_calls == [
        (
            "DEMO-B-0012 ready",
            {"client_request_id": f"speech-{response.json()['id']}", "source": "pushtotalk"},
        )
    ]
    assert kms_calls == [
        (
            "DEMO-B-0012 ready",
            {"client_request_id": f"speech-{response.json()['id']}", "source": "pushtotalk"},
        )
    ]
    assert response.json()["command_status"] == "needs_review"
    assert response.json()["reason"] == "Не понял этап."


def test_mqtt_error_falls_back_to_kms(client, monkeypatch) -> None:
    import app.api.speech as speech_api
    from app.services.mqtt_client import MqttPublishError

    kms_calls = []

    def fail_publish(text, **kwargs):
        raise MqttPublishError("broker down")

    monkeypatch.setattr(speech_api, "publish_text_command", fail_publish)
    monkeypatch.setattr(
        speech_api,
        "forward_text_command",
        lambda text, **kwargs: kms_calls.append((text, kwargs)) or {"status": "ok"},
    )

    response = client.post("/api/speech", json={"text": "DEMO-B-0012 ready"})

    assert response.status_code == 200
    assert kms_calls == [
        (
            "DEMO-B-0012 ready",
            {"client_request_id": f"speech-{response.json()['id']}", "source": "pushtotalk"},
        )
    ]


def test_transcribed_text_is_returned_without_early_dispatch(client, monkeypatch, tmp_path) -> None:
    import app.api.speech as speech_api

    calls = []
    monkeypatch.setattr(speech_api, "transcribe_audio", lambda path: "Batch DEMO-B-0012 finished mixing")
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
    assert response.json()["text"] == "Batch DEMO-B-0012 finished mixing"
    # Android sends the accepted text through POST /api/speech after its cancellable countdown.
    # Dispatching from the transcription endpoint too created two KMS voice messages.
    assert calls == []


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

    assert client.post("/api/speech", json={"text": "still alive"}).status_code == 200


def test_text_at_length_limit_is_accepted(client, settings) -> None:
    response = client.post("/api/speech", json={"text": "a" * settings.max_text_length})

    assert response.status_code == 200


def test_text_is_trimmed_before_saving(client) -> None:
    client.post("/api/speech", json={"text": "  hello world  "})

    assert client.get("/api/messages").json()[0]["text"] == "hello world"


def test_health_endpoint(client) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
