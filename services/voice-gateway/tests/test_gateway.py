import json
import urllib.error

from fastapi.testclient import TestClient

from app.config import Settings
from app.router import route_voice_event
from app.schemas import VoiceCommandEvent


def settings(**overrides):
    data = {
        "api_token": "",
        "project": "kms",
        "mqtt_host": "",
        "mqtt_port": 1883,
        "mqtt_username": "",
        "mqtt_password": "",
        "mqtt_tls": False,
        "mqtt_client_id": "test",
        "mqtt_topic": "voice/commands/recognized",
        "kms_command_url": "https://qms.example/api/pushtotalk/commands/",
        "kms_api_token": "secret",
        "http_timeout_seconds": 3,
    }
    data.update(overrides)
    return Settings(**data)


def test_project_mismatch_is_skipped_without_forwarding():
    event = VoiceCommandEvent(text="Партия DEMO-B-0012 закончила замес", project="crm")
    result = route_voice_event(event, settings(project="kms"))
    assert result.status == "skipped"
    assert result.reason == "project_mismatch"


def test_kms_adapter_sends_existing_command_payload(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"status": "ok", "command_id": 12}).encode()

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    event = VoiceCommandEvent(
        text="Партия DEMO-B-0012 закончила замес",
        request_id="phone-1",
        confidence=0.91,
        device_id="android-7",
        metadata={"room": "mixing"},
    )

    result = route_voice_event(event, settings())

    assert result.status == "ok"
    assert result.forwarded is True
    request, timeout = calls[0]
    assert timeout == 3
    assert request.headers["Authorization"] == "Bearer secret"
    body = json.loads(request.data.decode("utf-8"))
    assert body["text"] == "Партия DEMO-B-0012 закончила замес"
    assert body["client_request_id"] == "phone-1"
    assert body["source"] == "ovos"
    assert body["device_id"] == "android-7"


def test_kms_http_error_becomes_failed_route(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = route_voice_event(VoiceCommandEvent(text="команда"), settings())
    assert result.status == "failed"
    assert "HTTP 403" in result.reason


def test_missing_kms_config_is_skipped():
    result = route_voice_event(VoiceCommandEvent(text="команда"), settings(kms_command_url=""))
    assert result.status == "skipped"
    assert result.forwarded is False
    assert result.reason == "kms_not_configured"


def test_http_endpoint_requires_token(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "settings", settings(api_token="gateway-secret", kms_command_url=""))
    client = TestClient(main.app)
    response = client.post("/api/voice-events/", json={"text": "команда"})
    assert response.status_code == 403


def test_http_endpoint_routes_valid_event(monkeypatch):
    monkeypatch.setattr("app.main.route_voice_event", lambda event: {"status": "ok", "project": event.project, "forwarded": True})
    from app import main

    monkeypatch.setattr(main, "settings", settings(api_token="", kms_command_url=""))
    client = TestClient(main.app)
    response = client.post("/api/voice-events/", json={"text": "Партия DEMO-B-0012 готова"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
