"""Проверка пропуска, который QMS выдаёт человеку для входа в консоль.

Обратная сторона `apps/process_mining/console_token.py` в QMS. Подписывающий
секрет у обеих служб общий - тот же `PM_CALLBACK_SECRET`, которым подписывается
callback распознавания, - поэтому в подпись включено назначение: без него
пропуск и подпись callback стали бы взаимозаменяемы.

Формат: ``c1.<срок>.<подпись>``, где подпись - HMAC-SHA256 от строки
``console.<срок>``. Ни JSON, ни base64: разбирать это должен другой сервис на
другом языке, и каждый лишний слой кодирования - лишний способ разойтись.

Пропуск сознательно слабее мастер-ключа: он даёт только чтение и анализ.
Решение о том, что именно ему открыто, принимается в ``deps.require_api_key``
по пути запроса - приём событий и распознавание остаются за мастер-ключом.
"""

from __future__ import annotations

import hashlib
import hmac
import time

PURPOSE = "console"
VERSION = "c1"


def _signature(secret: str, expires_at: int) -> str:
    message = f"{PURPOSE}.{expires_at}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def is_console_token(value: str) -> bool:
    """Похоже ли на пропуск. Нужно, чтобы не звать проверку подписи на ключах."""
    return value.startswith(f"{VERSION}.")


def verify(value: str, secret: str, now: int | None = None) -> bool:
    """Подпись верна и срок не вышел."""
    if not secret or not is_console_token(value):
        return False
    parts = value.split(".")
    if len(parts) != 3:
        return False
    _, raw_expiry, presented = parts
    try:
        expires_at = int(raw_expiry)
    except ValueError:
        return False
    moment = int(time.time() if now is None else now)
    if expires_at < moment:
        return False
    # compare_digest, а не ==: сравнение строк выходит из цикла на первом
    # различии, и по времени ответа подпись можно подобрать посимвольно.
    return hmac.compare_digest(presented, _signature(secret, expires_at))
