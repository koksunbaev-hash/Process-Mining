from __future__ import annotations


def test_health_is_public(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_key_is_enforced(client, sample_events):
    response = client.post(
        "/api/v1/logs",
        json={"name": "x", "events": sample_events},
        headers={"X-API-Key": ""},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_full_lifecycle(client, sample_events):
    created = client.post(
        "/api/v1/logs",
        json={"name": "bakery", "events": sample_events, "mapping_profile": "bakery"},
    )
    assert created.status_code == 201
    log_id = created.json()["log_id"]
    assert created.json()["cases"] == 5

    stats = client.get(f"/api/v1/logs/{log_id}/statistics").json()
    assert stats["events"] == 25

    variants = client.get(f"/api/v1/logs/{log_id}/variants").json()
    assert variants["total_variants"] == 1

    discovered = client.post(
        f"/api/v1/logs/{log_id}/discover",
        json={"algorithm": "dfg_frequency", "format": "json"},
    ).json()
    assert len(discovered["graph"]["nodes"]) == 5
    assert discovered["graph"]["edges"]

    appended = client.post(
        f"/api/v1/logs/{log_id}/events",
        json={"events": [{"case_id": "B-9", "activity": "упаковали", "resource": "op-3"}]},
    ).json()
    assert appended["cases"] == 6

    assert client.delete(f"/api/v1/logs/{log_id}").status_code == 204
    assert client.get(f"/api/v1/logs/{log_id}").status_code == 404


def test_upload_and_stateless_mine(client, sample_csv):
    files = {"file": ("log.csv", sample_csv, "text/csv")}
    uploaded = client.post("/api/v1/logs/upload", files=files, data={"name": "csv"})
    assert uploaded.status_code == 201
    assert uploaded.json()["detected_columns"]["case_id"] == "batch"

    mined = client.post(
        "/api/v1/mine",
        files={"file": ("log.csv", sample_csv, "text/csv")},
        data={"algorithm": "dfg_frequency", "format": "json", "include_statistics": "true"},
    )
    assert mined.status_code == 200
    body = mined.json()
    assert body["result"]["graph"]["nodes"]
    assert body["statistics"]["cases"] == 5


def test_filters_shrink_the_model(client, sample_events):
    log_id = client.post(
        "/api/v1/logs", json={"name": "f", "events": sample_events}
    ).json()["log_id"]

    response = client.post(
        f"/api/v1/logs/{log_id}/discover",
        json={
            "algorithm": "dfg_frequency",
            "format": "json",
            "filters": {"activities_include": ["start_mixing", "proving"]},
        },
    ).json()
    labels = {node["label"] for node in response["graph"]["nodes"]}
    assert labels == {"start_mixing", "proving"}


def test_kpi_endpoints_take_the_same_filters(client, sample_events):
    """Отбор нужен и на GET: без него консоль не может сузить период."""
    log_id = client.post(
        "/api/v1/logs", json={"name": "f", "events": sample_events}
    ).json()["log_id"]

    full = client.get(f"/api/v1/logs/{log_id}/statistics").json()
    assert full["cases"] == 5
    assert full["activities"] == 5

    by_activity = client.get(
        f"/api/v1/logs/{log_id}/statistics",
        params={"activities": ["start_mixing", "proving"]},
    ).json()
    assert by_activity["activities"] == 2
    assert by_activity["events"] < full["events"]

    by_resource = client.get(
        f"/api/v1/logs/{log_id}/bottlenecks", params={"resources": ["op-1"]}
    )
    assert by_resource.status_code == 200

    # Первый кейс начинается в 09:00, каждый следующий часом позже.
    narrowed = client.get(
        f"/api/v1/logs/{log_id}/variants", params={"date_from": "2026-01-01T11:00:00"}
    ).json()
    assert narrowed["covered_cases"] < full["cases"]


def test_unfiltered_calls_are_unchanged(client, sample_events):
    """Пустой отбор не должен превращаться в фильтр: это другой ключ кэша."""
    log_id = client.post(
        "/api/v1/logs", json={"name": "f", "events": sample_events}
    ).json()["log_id"]

    plain = client.get(f"/api/v1/logs/{log_id}/statistics").json()
    with_empty = client.get(f"/api/v1/logs/{log_id}/statistics", params={}).json()
    assert plain == with_empty


def test_unknown_log_returns_404(client):
    response = client.get("/api/v1/logs/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
