"""Tiny content-addressed cache for discovery results.

Discovery is CPU-bound and deterministic: same log + same parameters means the
same answer. Dashboards poll, so caching turns a 3-second Petri net into a
2-millisecond lookup.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any


def fingerprint(*parts: Any) -> str:
    hasher = hashlib.blake2b(digest_size=16)
    for part in parts:
        hasher.update(json.dumps(part, sort_keys=True, default=str).encode("utf-8"))
    return hasher.hexdigest()


class TTLCache:
    """Thread-safe LRU + TTL cache. No Redis needed for a single container."""

    def __init__(self, max_items: int = 256, ttl_seconds: int = 900) -> None:
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max = max_items
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires_at, value = entry
            if expires_at < time.time():
                self._items.pop(key, None)
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = (time.time() + self._ttl, value)
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def invalidate_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [k for k in self._items if k.startswith(prefix)]
            for key in keys:
                self._items.pop(key, None)
            return len(keys)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"size": len(self._items), "hits": self.hits, "misses": self.misses}
