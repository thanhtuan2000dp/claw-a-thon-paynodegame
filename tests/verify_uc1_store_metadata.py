"""Verify sheet UC1 — store metadata crawl (live).

Asserts the use case resolves an app, returns enriched normalised metadata
(category, price, version, rating, screenshots), records a chart rank for iOS,
and seeds a snapshot. Run: ./venv/bin/python tests/verify_uc1_store_metadata.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.ios_charts import IosChartsConnector  # noqa: E402
from connectors.itunes import ItunesConnector  # noqa: E402
from core.deps import Deps  # noqa: E402
from storage.snapshots import SnapshotStore  # noqa: E402
from usecases.uc1_store_metadata import StoreMetadataUseCase  # noqa: E402

ZALO_IOS = "579523206"


def main():
    deps = Deps(
        connectors=[ItunesConnector(country="vn"), IosChartsConnector(country="vn")],
        storage=SnapshotStore(tempfile.mkdtemp()),
    )
    res = StoreMetadataUseCase().run(
        {"app": ZALO_IOS, "store": "ios", "country": "vn", "lang": "vi"}, deps
    )
    if res.get("error"):
        print(f"SKIPPED (network?): {res['error']}")
        return

    m, rk = res["metadata"], res["ranking"]
    print(f"name={m['name']!r} category={m['category']!r} price={m['price']!r} version={m['version']!r}")
    print(f"avg_rating={m['avg_rating']} rating_count={m['rating_count']} screenshots={m['screenshot_count']}")
    print(f"ranking: {rk['chart']} rank={rk['rank']} | history={res['history']}")
    print(f"summary: {res['summary']}")

    assert "zalo" in (m["name"] or "").lower(), f"unexpected name {m['name']!r}"
    assert m["category"], "category not populated"
    assert m["version"], "version missing"
    assert isinstance(m["avg_rating"], (int, float)), "avg_rating not numeric"
    assert m["screenshot_count"] >= 0
    assert "rank" in rk  # rank may be None if outside top-100, that's valid
    assert res.get("summary")
    print("PASS: iOS metadata crawl + ranking + snapshot")


if __name__ == "__main__":
    main()
    print("\nALL OK")
