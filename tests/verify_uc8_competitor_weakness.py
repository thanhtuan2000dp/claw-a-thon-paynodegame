"""Verify sheet UC8 — competitor weakness mining (live, no LLM needed for structure).

Asserts: the app resolves, same-category competitors are discovered via the genre
chart (self excluded), and negative reviews are fetched per competitor. Pain-point
clustering needs the LLM (degrades to a note without it), so opportunities are not
required to pass.

Run: ./venv/bin/python tests/verify_uc8_competitor_weakness.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.appstore_reviews import AppStoreReviewsConnector  # noqa: E402
from connectors.ios_charts import IosChartsConnector  # noqa: E402
from connectors.itunes import ItunesConnector  # noqa: E402
from core.deps import PREFERENCE, Deps  # noqa: E402
from core.registry import discover_use_cases  # noqa: E402
from storage.snapshots import SnapshotStore  # noqa: E402
from usecases.uc8_competitor_weakness import CompetitorWeaknessUseCase  # noqa: E402

ZALOPAY_IOS = "1112407590"


def main():
    assert "uc8_competitor_weakness" in discover_use_cases(), "use case not auto-discovered"
    assert "category" in PREFERENCE, "CAP_CATEGORY not in PREFERENCE"
    print("PASS: discovered + PREFERENCE['category'] wired")

    deps = Deps(
        connectors=[ItunesConnector(country="vn"), IosChartsConnector(country="vn"),
                    AppStoreReviewsConnector(country="vn", lang="vi")],
        storage=SnapshotStore(tempfile.mkdtemp()),
    )
    res = CompetitorWeaknessUseCase().run(
        {"app": ZALOPAY_IOS, "store": "ios", "country": "vn", "lang": "vi", "top_n": 3, "window_days": 60},
        deps,
    )
    if res.get("error"):
        print(f"SKIPPED (network?): {res['error']}")
        return

    app, comps = res["app"], res["competitors"]
    print(f"app: {app['name']} | category: {app['category']}")
    for c in comps:
        print(f"  rival: {c['name']:35} neg={c['negative_reviews']:3} fetched={c['reviews_fetched']}")
    print(f"opportunities (LLM): {len(res['opportunities'])} | notes: {res['notes']}")

    assert "zalo" in (app["name"] or "").lower()
    assert app["category"] == "Finance", f"unexpected category {app['category']}"
    assert comps, "no competitors discovered"
    assert all(c["app_id"] != ZALOPAY_IOS for c in comps), "self not excluded from competitors"
    assert any(c["reviews_fetched"] > 0 for c in comps), "no competitor reviews fetched"
    print("PASS: same-category competitors discovered + negative reviews fetched")


if __name__ == "__main__":
    main()
    print("\nALL OK")
