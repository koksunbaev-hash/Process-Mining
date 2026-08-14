"""Пропуск в консоль: принимается на чтение, не открывает приём событий."""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient

from app import console_token
from app.config import Settings
from app.main import create_app

SECRET = "shared-callback-secret"


@pytest.fixture
def console_settings(tmp_path) -> Settings:
    return Settings(
        environment="local",
        storage_backend="memory",
        api_keys="master-key",
        callback_secret=SECRET,
        artifact_dir=tmp_path / "artifacts",
        sqlite_path=tmp_path / "pm.db",
        mapping_config="config/activities.yaml",
        log_json=False,
        voice_enabled=False,
    )


@pytest.fixture
def console_client(console_settings) -> TestClient:
    with TestClient(create_app(console_settings)) as client:
        yield client


def make_pass(ttl: int = 3600, now: int | None = None) -> str:
    expires_at = int(time.time() if now is None else now) + ttl
    return f"{console_token.VERSION}.{expires_at}.{console_token._signature(SECRET, expires_at)}"


class TestVerification:
    def test_fresh_pass_verifies(self):
        assert console_token.verify(make_pass(), SECRET)

    def test_expired_pass_is_refused(self):
        assert not console_token.verify(make_pass(ttl=-1), SECRET)

    def test_tampered_expiry_is_refused(self):
        """Срок входит в подпись — сдвинуть его в одиночку нельзя."""
        version, expiry, signature = make_pass().split(".")
        forged = f"{version}.{int(expiry) + 86400}.{signature}"
        assert not console_token.verify(forged, SECRET)

    def test_another_secret_is_refused(self):
        assert not console_token.verify(make_pass(), "someone-elses-secret")

    def test_a_signature_for_another_purpose_is_not_a_pass(self):
        """Секрет общий с callback распознавания, поэтому в подпись входит назначение."""
        expires_at = int(time.time()) + 3600
        signature = hmac.new(
            SECRET.encode(), f"callback.{expires_at}".encode(), hashlib.sha256
        ).hexdigest()
        assert not console_token.verify(f"c1.{expires_at}.{signature}", SECRET)

    def test_a_plain_key_is_not_mistaken_for_a_pass(self):
        assert not console_token.is_console_token("master-key")


class TestWhatThePassOpens:
    def test_analysis_endpoint_accepts_the_pass(self, console_client):
        response = console_client.get("/api/v1/logs", headers={"X-API-Key": make_pass()})
        assert response.status_code == 200

    def test_ingest_endpoint_refuses_the_pass(self, console_client):
        """Приём событий — запись, и пропуск её не открывает."""
        response = console_client.post(
            "/api/event-logs/import/",
            headers={"X-API-Key": make_pass()},
            json={"events": []},
        )
        assert response.status_code == 401
        assert "read-only" in response.text

    def test_ingest_endpoint_still_takes_the_master_key(self, console_client):
        response = console_client.post(
            "/api/event-logs/import/",
            headers={"X-API-Key": "master-key"},
            json={"events": []},
        )
        assert response.status_code != 401

    def test_expired_pass_says_what_to_do(self, console_client):
        response = console_client.get("/api/v1/logs", headers={"X-API-Key": make_pass(ttl=-1)})
        assert response.status_code == 401
        assert "expired" in response.text.lower()

    def test_master_key_keeps_working_on_analysis(self, console_client):
        response = console_client.get("/api/v1/logs", headers={"X-API-Key": "master-key"})
        assert response.status_code == 200
