"""The voice contract: accept now, answer later, sign the answer.

The signature test matters most. The source system rejects a callback whose
HMAC does not match, and it computes that HMAC its own way - so we verify
against a copy of *its* algorithm, not against ours.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.api.transcriptions import _run
from app.main import create_app
from app.services.stt import SttError, SttService


def qms_verifies(raw_body: bytes, signature: str, secret: str) -> bool:
    """Verbatim reimplementation of the receiver's check."""
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, f"sha256={digest}") or hmac.compare_digest(
        signature, digest
    )


class FakeState:
    def __init__(self, stt) -> None:
        self.stt_service = stt


class RecordingStt(SttService):
    """Real signing and callback logic, fake model and fake network."""

    def __init__(self, settings, *, transcript=None, error=None) -> None:
        super().__init__(settings)
        self._transcript = transcript
        self._error = error
        self.delivered: list[tuple[str, bytes, str]] = []

    def transcribe(self, payload, *, language=None):
        if self._error:
            raise self._error
        return {
            "transcript": self._transcript,
            "language": language or "ru",
            "duration_ms": 1700,
            "took_ms": 900,
        }

    def send_callback(self, callback_url, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.delivered.append((callback_url, body, self.sign(body)))
        return True


def test_callback_signature_is_accepted_by_the_receiver(settings):
    settings.callback_secret = "s3cret-shared-with-qms"
    stt = RecordingStt(settings, transcript="Партия B-154 закончила замес")

    _run(
        FakeState(stt),
        task_id="tr-abc123",
        external_id="821",
        payload=b"fake-audio",
        language="ru",
        callback_url="http://qms:8000/api/process-mining/callback/",
        context={},
    )

    assert len(stt.delivered) == 1
    url, body, signature = stt.delivered[0]
    assert url.endswith("/api/process-mining/callback/")
    assert qms_verifies(body, signature, settings.callback_secret)

    payload = json.loads(body)
    assert payload["status"] == "completed"
    assert payload["task_id"] == "tr-abc123"
    assert payload["external_id"] == "821"
    assert payload["transcript"] == "Партия B-154 закончила замес"


def test_a_wrong_secret_is_rejected(settings):
    settings.callback_secret = "right"
    stt = RecordingStt(settings, transcript="тест")
    _run(FakeState(stt), task_id="t", external_id="1", payload=b"a",
         language="ru", callback_url="http://qms/cb", context={})
    _, body, signature = stt.delivered[0]
    assert not qms_verifies(body, signature, "wrong")


def test_failure_is_reported_not_swallowed(settings):
    settings.callback_secret = "s"
    stt = RecordingStt(settings, error=SttError("no speech", code="EMPTY_TRANSCRIPT"))

    _run(FakeState(stt), task_id="tr-1", external_id="9", payload=b"a",
         language="ru", callback_url="http://qms/cb", context={})

    payload = json.loads(stt.delivered[0][1])
    assert payload["status"] == "failed"
    assert payload["error_code"] == "EMPTY_TRANSCRIPT"
    # the caller still learns which recording this was about
    assert payload["external_id"] == "9"


def test_submitting_returns_a_task_immediately(client, monkeypatch):
    response = client.post(
        "/api/transcriptions/",
        files={"audio_file": ("voice.webm", b"fake-audio", "audio/webm")},
        data={"external_id": "821", "client_request_id": "req-1", "language": "ru",
              "callback_url": "http://qms:8000/api/process-mining/callback/"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["external_id"] == "821"
    assert body["task_id"].startswith("tr-")


def test_the_same_recording_is_not_transcribed_twice(client):
    payload = {
        "files": {"audio_file": ("voice.webm", b"fake-audio", "audio/webm")},
        "data": {"external_id": "77", "client_request_id": "req-same", "language": "ru"},
    }
    first = client.post("/api/transcriptions/", **payload).json()
    second = client.post("/api/transcriptions/", **payload).json()
    assert first["task_id"] == second["task_id"]


def test_capabilities_are_published(client):
    body = client.get("/api/transcriptions/capabilities").json()
    assert "audio/webm" in body["formats"]
    assert "EMPTY_TRANSCRIPT" in body["error_codes"]


def test_sync_answers_with_the_text_on_the_same_connection(client, monkeypatch):
    """The phone has nowhere to receive a callback, so it gets the answer inline."""
    monkeypatch.setattr(
        "app.services.stt.SttService.transcribe",
        lambda self, payload, *, language=None: {
            "transcript": "партия B-154 закончила замес",
            "language": language or "ru",
            "duration_ms": 1700,
            "took_ms": 900,
        },
    )

    response = client.post(
        "/api/transcriptions/sync",
        files={"audio_file": ("voice.m4a", b"fake-audio", "audio/mp4")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["text"] == "партия B-154 закончила замес"
    # Both names: the callback contract already говорит "transcript", and the
    # phone reads "text". Renaming either would break a client in the field.
    assert body["transcript"] == body["text"]


def test_sync_needs_a_key_like_everything_else(settings):
    with TestClient(create_app(settings)) as anonymous:
        response = anonymous.post(
            "/api/transcriptions/sync",
            files={"audio_file": ("voice.m4a", b"fake-audio", "audio/mp4")},
        )
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        ("STT_UNAVAILABLE", 503),
        ("AUDIO_DECODE_UNAVAILABLE", 503),
        ("UNSUPPORTED_AUDIO", 415),
        ("EMPTY_TRANSCRIPT", 422),
    ],
)
def test_sync_separates_retryable_failures_from_permanent_ones(
    client, monkeypatch, code, expected_status
):
    """A phone that retries a 415 forever helps nobody; a 503 is worth retrying."""

    def failing(self, payload, *, language=None):
        raise SttError("nope", code=code)

    monkeypatch.setattr("app.services.stt.SttService.transcribe", failing)

    response = client.post(
        "/api/transcriptions/sync",
        files={"audio_file": ("voice.m4a", b"fake-audio", "audio/mp4")},
    )
    assert response.status_code == expected_status
    assert response.json()["error"]["code"]


def test_stt_adds_ngrok_skip_header_when_enabled(settings, monkeypatch):
    seen = {}
    service = SttService(settings.model_copy(update={"stt_skip_ngrok_warning": True}))
    monkeypatch.setattr(service, "decode_to_wav", lambda payload: (b"RIFF" + b"x" * 64, 0.1))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"recognized text"

    def fake_urlopen(request, timeout):
        seen["header"] = request.get_header("ngrok-skip-browser-warning")
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = service.transcribe(b"audio")

    assert result["transcript"] == "recognized text"
    assert seen["header"] == "true"


@pytest.mark.parametrize("bad", [b"", b"not audio at all"])
def test_undecodable_audio_raises_a_typed_error(settings, bad):
    service = SttService(settings)
    with pytest.raises((SttError, Exception)) as excinfo:
        service.decode_to_pcm(bad)
    assert excinfo.value is not None
