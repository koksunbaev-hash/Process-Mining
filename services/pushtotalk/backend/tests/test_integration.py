"""Сквозные сценарии: запрос клиента → запись в SQLite → история."""

from __future__ import annotations

from app.database.models import SpeechMessage


def test_full_round_trip(client, db_engine) -> None:
    """Полный путь реплики так, как его проходит Android-клиент."""
    from sqlalchemy.orm import sessionmaker

    post = client.post("/api/speech", json={"text": "Проверка связи"})

    assert post.status_code == 200
    message_id = post.json()["id"]

    # 1. Запись действительно легла в SQLite.
    factory = sessionmaker(bind=db_engine, future=True)
    with factory() as session:
        stored = session.get(SpeechMessage, message_id)
        assert stored is not None
        assert stored.text == "Проверка связи"
        assert stored.status == "received"

    # 2. И видна через публичный endpoint истории.
    history = client.get("/api/messages").json()
    assert history[0]["id"] == message_id
    assert history[0]["text"] == "Проверка связи"


def test_several_clients_in_sequence(client) -> None:
    texts = ["первая реплика", "вторая реплика", "третья реплика"]
    for text in texts:
        assert client.post("/api/speech", json={"text": text}).status_code == 200

    history = [item["text"] for item in client.get("/api/messages").json()]

    assert history == list(reversed(texts))


def test_rejected_request_does_not_break_following_ones(client) -> None:
    client.post("/api/speech", json={"text": ""})
    client.post("/api/speech", content=b"{broken", headers={"Content-Type": "application/json"})

    assert client.post("/api/speech", json={"text": "после ошибок"}).status_code == 200
    assert client.get("/api/messages").json()[0]["text"] == "после ошибок"


def test_request_is_written_to_log(client, settings) -> None:
    from app.logging_setup import configure_logging

    configure_logging(settings)
    client.post("/api/speech", json={"text": "запись в лог"})

    for handler in __import__("logging").getLogger().handlers:
        handler.flush()

    assert settings.log_file.exists()
    contents = settings.log_file.read_text(encoding="utf-8")
    assert "POST /api/speech" in contents
    # Сам текст в лог не попадает — только его длина.
    assert "запись в лог" not in contents
    assert "text_length=" in contents
