from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        environment="local",
        storage_backend="memory",
        api_keys="test-key",
        artifact_dir=tmp_path / "artifacts",
        sqlite_path=tmp_path / "pm.db",
        mapping_config="config/activities.yaml",
        log_json=False,
        voice_enabled=False,
    )


@pytest.fixture
def client(settings) -> TestClient:
    with TestClient(create_app(settings)) as test_client:
        test_client.headers.update({"X-API-Key": "test-key"})
        yield test_client


@pytest.fixture
def sample_events() -> list[dict]:
    base = datetime(2026, 1, 1, 8, 0)
    steps = ["start_mixing", "add_ingredients", "proving", "load_oven", "unload_oven"]
    events = []
    for case in range(1, 6):
        moment = base + timedelta(hours=case)
        for index, step in enumerate(steps):
            events.append(
                {
                    "case_id": f"B-{case}",
                    "activity": step,
                    "timestamp": (moment + timedelta(minutes=15 * index)).isoformat(),
                    "resource": "op-1" if case % 2 else "op-2",
                }
            )
    return events


@pytest.fixture
def sample_csv(sample_events) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["batch", "step", "event_time", "operator"])
    writer.writeheader()
    for event in sample_events:
        writer.writerow(
            {
                "batch": event["case_id"],
                "step": event["activity"],
                "event_time": event["timestamp"],
                "operator": event["resource"],
            }
        )
    return buffer.getvalue().encode("utf-8")
