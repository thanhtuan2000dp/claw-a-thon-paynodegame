"""Verify the TTL cache: basic store/expiry, the decorator memoises a connector
method (runs the body once for repeated args), and datetimes key at day
granularity. No network. Run: ./venv/bin/python tests/verify_cache.py
"""
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cache import TTLCache, ttl_cache  # noqa: E402


def main():
    # store + expiry
    c = TTLCache()
    c.set("k", 42, 10)
    assert c.get("k") == 42
    c.set("k2", 1, 0.01)
    time.sleep(0.05)
    assert c.get("k2") is None, "entry should have expired"

    # decorator memoises: body runs once for repeated args, skips self in the key
    class Fake:
        name = "fake"
        calls = 0

        @ttl_cache(10)
        def fetch(self, a, b=None):
            Fake.calls += 1
            return (a, b, Fake.calls)

    f = Fake()
    r1 = f.fetch("x", b="y")
    r2 = f.fetch("x", b="y")
    assert r1 == r2 and Fake.calls == 1, (r1, r2, Fake.calls)
    f.fetch("z", b="y")
    assert Fake.calls == 2, "different args must re-run"

    # datetimes normalise to day -> same-day calls share the entry
    Fake.calls = 0
    f.fetch(datetime(2026, 6, 15, 1, 0, 0))
    f.fetch(datetime(2026, 6, 15, 23, 30, 0))
    assert Fake.calls == 1, "same-day datetimes should share the cache key"
    print("PASS: TTL cache store/expiry + decorator memoisation + datetime-day keying")


if __name__ == "__main__":
    main()
    print("\nALL OK")
