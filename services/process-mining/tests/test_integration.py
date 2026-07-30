"""The event-log intake contract a source system was built against.

These tests pin the behaviour that makes automated ingestion safe: a batch that
arrives twice must not be imported twice, and a row the source got wrong must
be reported without taking the rest of the batch down with it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

COLUMNS = [
    "event_id", "case_id", "case_type", "activity", "timestamp", "user_id", "user_name",
    "resource", "product_id", "product_name", "batch_number", "order_number",
    "from_stage", "to_stage", "status", "quantity", "unit", "problem_type", "metadata",
]
STAGES = ["Очередь", "Замес", "Печь"]
TZ = timezone(timedelta(hours=5))


def build_csv(cases: int = 3, *, extra_rows: list[dict] | None = None) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    start = datetime(2026, 7, 20, 6, 0, tzinfo=TZ)
    for case in range(1, cases + 1):
        moment = start + timedelta(hours=case * 3)
        previous = ""
        for index, stage in enumerate(STAGES):
            moment += timedelta(minutes=30 + index * 15)
            writer.writerow(
                dict.fromkeys(COLUMNS, "")
                | {
                    "event_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{case}-{stage}")),
                    "case_id": f"B-{case:04d}",
                    "case_type": "production_batch",
                    "activity": stage,
                    "timestamp": moment.isoformat(),
                    "resource": f"line-{case % 2 + 1}",
                    "from_stage": previous,
                    "to_stage": stage,
                    "metadata": json.dumps({"line": case % 2 + 1}),
                }
            )
            previous = stage
    for row in extra_rows or []:
        writer.writerow(dict.fromkeys(COLUMNS, "") | row)
    return buffer.getvalue().encode("utf-8")


def post_batch(client, payload: bytes, *, export_id: str, key: str | None = None,
               source: str = "kms_bakery", checksum: str | None = None):
    return client.post(
        "/api/event-logs/import/",
        files={"file": ("events.csv", payload, "text/csv")},
        data={
            "export_id": export_id,
            "source": source,
            "schema_version": "1.0",
            "checksum": hashlib.sha256(payload).hexdigest() if checksum is None else checksum,
            "events_count": payload.decode("utf-8").count("\n") - 1,
        },
        headers={"Idempotency-Key": key or export_id},
    )


def test_import_accepts_a_batch(client):
    payload = build_csv(cases=3)
    response = post_batch(client, payload, export_id=str(uuid.uuid4()))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["received"] == 9
    assert body["accepted"] == 9
    assert body["duplicates"] == 0
    assert body["rejected"] == 0
    assert len(body["log_ids"]) == 1


def test_replaying_a_batch_returns_the_original_answer(client):
    payload = build_csv(cases=2)
    export_id = str(uuid.uuid4())

    first = post_batch(client, payload, export_id=export_id).json()
    second = post_batch(client, payload, export_id=export_id).json()

    assert second == first
    # and nothing was imported a second time
    log_id = first["log_ids"][0]
    summary = client.get(f"/api/v1/logs/{log_id}").json()
    assert summary["events"] == first["accepted"]


def test_same_events_in_a_new_batch_are_duplicates(client):
    payload = build_csv(cases=2)
    post_batch(client, payload, export_id=str(uuid.uuid4()))

    again = post_batch(client, payload, export_id=str(uuid.uuid4())).json()

    assert again["accepted"] == 0
    assert again["duplicates"] == 6


def test_bad_rows_are_reported_without_losing_the_batch(client):
    payload = build_csv(
        cases=1,
        extra_rows=[
            {"event_id": "no-timestamp", "case_id": "B-0001",
             "case_type": "production_batch", "activity": "X", "timestamp": "not a date"},
            {"event_id": "", "case_id": "B-0001", "case_type": "production_batch",
             "activity": "X", "timestamp": "2026-07-20T06:00:00+05:00"},
            {"event_id": "no-case", "case_id": "", "case_type": "production_batch",
             "activity": "X", "timestamp": "2026-07-20T06:00:00+05:00"},
        ],
    )
    body = post_batch(client, payload, export_id=str(uuid.uuid4())).json()

    assert body["status"] == "partially_accepted"
    assert body["accepted"] == 3
    assert body["rejected"] == 3
    codes = {error["code"] for error in body["errors"]}
    assert codes == {"INVALID_TIMESTAMP", "MISSING_EVENT_ID", "MISSING_CASE_ID"}


def test_checksum_mismatch_is_refused(client):
    payload = build_csv(cases=1)
    response = post_batch(client, payload, export_id=str(uuid.uuid4()), checksum="deadbeef")

    assert response.status_code == 422
    assert response.json()["error"]["details"]["code"] == "CHECKSUM_MISMATCH"


def test_case_types_land_in_separate_logs(client):
    payload = build_csv(
        cases=1,
        extra_rows=[
            {"event_id": str(uuid.uuid4()), "case_id": "ORD-1", "case_type": "production_order",
             "activity": "confirmed", "timestamp": "2026-07-20T06:00:00+05:00"},
        ],
    )
    body = post_batch(client, payload, export_id=str(uuid.uuid4())).json()

    assert len(body["log_ids"]) == 2
    names = {
        client.get(f"/api/v1/logs/{log_id}").json()["name"] for log_id in body["log_ids"]
    }
    assert names == {"kms_bakery · production_batch", "kms_bakery · production_order"}


def test_imported_log_is_minable(client):
    payload = build_csv(cases=4)
    log_id = post_batch(client, payload, export_id=str(uuid.uuid4())).json()["log_ids"][0]

    stats = client.get(f"/api/v1/logs/{log_id}/statistics").json()
    assert stats["cases"] == 4
    assert stats["activities"] == len(STAGES)

    discovered = client.post(
        f"/api/v1/logs/{log_id}/discover",
        json={"algorithm": "dfg_frequency", "format": "json"},
    ).json()
    assert {node["label"] for node in discovered["graph"]["nodes"]} == set(STAGES)


def test_missing_required_column_is_rejected(client):
    payload = b"case_id,activity,timestamp\nB-1,mix,2026-07-20T06:00:00+05:00\n"
    response = post_batch(client, payload, export_id=str(uuid.uuid4()))

    assert response.status_code == 422
    assert response.json()["error"]["details"]["code"] == "INVALID_SCHEMA"


def test_append_endpoint_is_idempotent_too(client, sample_events):
    """The JSON push path gets the same protection as the CSV batch path."""
    log_id = client.post(
        "/api/v1/logs", json={"name": "push", "events": sample_events}
    ).json()["log_id"]

    event = {"event_id": "evt-1", "case_id": "B-9", "activity": "packed"}
    first = client.post(f"/api/v1/logs/{log_id}/events", json={"events": [event]}).json()
    second = client.post(f"/api/v1/logs/{log_id}/events", json={"events": [event]}).json()

    assert second["events"] == first["events"]


@pytest.mark.parametrize("suffix", ["/api/event-logs/import/", "/api/event-logs/import"])
def test_both_slash_forms_reach_the_endpoint(client, suffix):
    payload = build_csv(cases=1)
    response = client.post(
        suffix,
        files={"file": ("e.csv", payload, "text/csv")},
        data={"export_id": str(uuid.uuid4()), "source": "kms_bakery"},
        follow_redirects=True,
    )
    assert response.status_code == 200
