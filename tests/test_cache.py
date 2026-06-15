"""Offline tests for the TTL cache (core.cache)."""
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cache import TTLCache, ttl_cache  # noqa: E402


def test_store_and_expiry():
    c = TTLCache()
    c.set("k", 42, 10)
    assert c.get("k") == 42
    c.set("e", 1, 0.01)
    time.sleep(0.05)
    assert c.get("e") is None


def test_memoise_skips_self_and_reuses():
    class F:
        name = "f"
        calls = 0

        @ttl_cache(10)
        def fetch(self, a, b=None):
            F.calls += 1
            return (a, b, F.calls)

    f = F()
    assert f.fetch("x", b="y") == f.fetch("x", b="y")
    assert F.calls == 1
    f.fetch("z", b="y")
    assert F.calls == 2


def test_datetime_keys_at_day_granularity():
    class F:
        name = "f2"
        calls = 0

        @ttl_cache(10)
        def fetch(self, when):
            F.calls += 1
            return when

    f = F()
    f.fetch(datetime(2026, 6, 15, 1, 0, 0))
    f.fetch(datetime(2026, 6, 15, 23, 30, 0))
    assert F.calls == 1
