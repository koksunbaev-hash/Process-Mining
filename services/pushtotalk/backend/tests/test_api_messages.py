"""Тесты GET /api/messages."""

from __future__ import annotations


def test_empty_history(client) -> None:
    response = client.get("/api/messages")

    assert response.status_code == 200
    assert response.json() == []


def test_history_contains_sent_message(client) -> None:
    client.post("/api/speech", json={"text": "hello"})

    body = client.get("/api/messages").json()

    assert len(body) == 1
    assert body[0]["text"] == "hello"
    assert body[0]["status"] == "received"
    assert body[0]["created_at"]


def test_newest_message_first(client) -> None:
    for text in ("message1", "message2", "message3"):
        assert client.post("/api/speech", json={"text": text}).status_code == 200

    texts = [item["text"] for item in client.get("/api/messages").json()]

    assert texts == ["message3", "message2", "message1"]


def test_history_is_capped_at_fifty(client) -> None:
    for index in range(55):
        client.post("/api/speech", json={"text": f"message-{index}"})

    body = client.get("/api/messages").json()

    assert len(body) == 50
    assert body[0]["text"] == "message-54"


def test_limit_parameter_narrows_result(client) -> None:
    for text in ("one", "two", "three"):
        client.post("/api/speech", json={"text": text})

    body = client.get("/api/messages", params={"limit": 2}).json()

    assert [item["text"] for item in body] == ["three", "two"]


def test_limit_above_maximum_is_rejected(client) -> None:
    assert client.get("/api/messages", params={"limit": 500}).status_code == 422


def test_limit_below_one_is_rejected(client) -> None:
    assert client.get("/api/messages", params={"limit": 0}).status_code == 422
