"""Пропуск в консоль аналитики вместо ручного ввода ключа.

Раньше человек открывал консоль и упирался в поле «API key». Ключ у него взять
неоткуда — это `PM_API_KEYS`, общий мастер-ключ развёртывания, который открывает
не только чтение аналитики, но и приём событий. Просить клиента его искать и
вставлять значило раздавать этот ключ по рукам.

Здесь QMS подписывает короткоживущий пропуск на секрете, который у обеих сторон
и так общий (`PM_CALLBACK_SECRET`), и кладёт его в якорь ссылки. Якорь выбран
намеренно: он не уходит на сервер, поэтому не оседает в журналах прокси.

Три свойства, ради которых это сделано именно так:

- **мастер-ключ не покидает сервер** — клиент его не видит и не может передать
  дальше;
- **пропуск протухает** — пересланная ссылка перестаёт работать сама, без
  отзыва и списков;
- **пропуск не даёт писать** — аналитика принимает его только на `/api/v1`,
  а приём событий и распознавание остаются за мастер-ключом.

Формат сознательно примитивный: `c1.<срок>.<подпись>`. Разбирать его будет
чужой сервис на другом языке, и всякий JSON или base64 здесь только добавил бы
способов разойтись в мелочах.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from django.conf import settings

#: Метка назначения внутри подписи. Тот же секрет подписывает callback
#: распознавания, и без разделения пропуск можно было бы подсунуть туда.
PURPOSE = "console"
VERSION = "c1"


def _signature(secret: str, expires_at: int) -> str:
    message = f"{PURPOSE}.{expires_at}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def issue(ttl_seconds: int | None = None, now: int | None = None) -> str:
    """Пропуск, действительный указанное время. Пустая строка - если нечем подписать."""
    secret = settings.PROCESS_MINING_CALLBACK_SECRET
    if not secret:
        return ""
    ttl = settings.PROCESS_MINING_CONSOLE_TOKEN_TTL if ttl_seconds is None else ttl_seconds
    expires_at = int(now if now is not None else time.time()) + int(ttl)
    return f"{VERSION}.{expires_at}.{_signature(secret, expires_at)}"


def console_link() -> str:
    """Адрес консоли с пропуском в якоре, или пустая строка, если адрес не задан."""
    base = (settings.PROCESS_MINING_CONSOLE_URL or "").rstrip("/")
    if not base:
        return ""
    token = issue()
    return f"{base}/#t={token}" if token else f"{base}/"
