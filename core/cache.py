"""Tiny thread-safe in-process TTL cache for connector fetches.

Cuts repeat network calls — and the App Store / Google Play HTTP 429s that follow
— when use cases re-fetch the same app inside a short window: e.g. UC7/UC8/UC10
pull metadata for several competitors, and the genre chart is reused across
UC1/UC7/UC8. Cache keys ignore ``self`` and normalise datetimes to day
granularity so two windows that differ only by the current second still share an
entry. In-process only (per worker); for cross-instance reuse, back it with a
shared store (e.g. AgentBase Memory) behind the same interface.

Only successful return values are cached — a raised ``ConnectorError`` propagates
and is retried next call.
"""

from __future__ import annotations

import functools
import threading
import time
from datetime import date, datetime
from typing import Callable


class TTLCache:
    def __init__(self) -> None:
        self._store: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._store.get(key)
            if hit is None:
                return None
            value, expires = hit
            if expires < time.time():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key, value, ttl: float) -> None:
        with self._lock:
            self._store[key] = (value, time.time() + ttl)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_CACHE = TTLCache()


def _norm(arg):
    """Day-granular for datetimes so review windows that differ only by a few
    seconds (each call recomputes `now`) still hit the same cache entry."""
    if isinstance(arg, datetime):
        return arg.date().isoformat()
    if isinstance(arg, date):
        return arg.isoformat()
    return arg


def ttl_cache(seconds: float) -> Callable:
    """Decorator: cache a connector method's successful result for ``seconds``.
    Keys on (connector name, method, args[1:], kwargs) with datetimes normalised."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            owner = args[0] if args else None
            owner_id = getattr(owner, "name", owner.__class__.__name__ if owner else "")
            key = (
                owner_id,
                fn.__qualname__,
                tuple(_norm(a) for a in args[1:]),
                tuple(sorted((k, _norm(v)) for k, v in kwargs.items())),
            )
            cached = _CACHE.get(key)
            if cached is not None:
                return cached
            value = fn(*args, **kwargs)
            _CACHE.set(key, value, seconds)
            return value

        return wrapper

    return decorator


# Shared TTLs (seconds). App Store responses advertise max-age=900; charts/metadata
# move slowly, so 15 min is safe and cuts repeat fetches within a query/session.
TTL_METADATA = 900
TTL_REVIEWS = 900
TTL_CHART = 900
TTL_SEARCH = 3600
