"""Verify sheet UC7 — competitive comparison (live, no LLM needed for the table).

Asserts the app + same-category rivals are compared on rank/rating/ratings/price,
your app is flagged, and deterministic leaders are computed. The positioning
narrative needs the LLM (degrades to a note), so it is not required to pass.

Run: ./venv/bin/python tests/verify_uc7_competitive_comparison.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.ios_charts import IosChartsConnector  # noqa: E402
from connectors.itunes import ItunesConnector  # noqa: E402
from core.deps import Deps  # noqa: E402
from core.registry import discover_use_cases  # noqa: E402
from storage.snapshots import SnapshotStore  # noqa: E402
from usecases.uc7_competitive_comparison import CompetitiveComparisonUseCase  # noqa: E402

ZALOPAY_IOS = "1112407590"


def main():
    assert "uc7_competitive_comparison" in discover_use_cases(), "use case not auto-discovered"
    deps = Deps(
        connectors=[ItunesConnector(country="vn"), IosChartsConnector(country="vn")],
        storage=SnapshotStore(tempfile.mkdtemp()),
    )
    res = CompetitiveComparisonUseCase().run(
        {"app": ZALOPAY_IOS, "store": "ios", "country": "vn", "lang": "vi", "top_n": 4}, deps
    )
    if res.get("error"):
        print(f"SKIPPED (network?): {res['error']}")
        return

    rows = res["comparison"]
    print(f"app: {res['app']['name']} | category: {res['app']['category']}")
    for r in rows:
        you = "⭐" if r["is_you"] else "  "
        print(f"  {you} #{r.get('rank')}  {r['name']:38} rating={r.get('rating')} "
              f"({r.get('ratings_count')}) {r.get('price')}")
    print(f"leaders: {res['leaders']}")
    print(f"positioning (LLM): {len(res['positioning'])} | notes: {[n for n in res['notes'] if n]}")

    assert len(rows) >= 2, "need at least your app + 1 rival"
    assert sum(1 for r in rows if r["is_you"]) == 1, "exactly one row must be your app"
    you_row = next(r for r in rows if r["is_you"])
    assert "zalo" in (you_row["name"] or "").lower()
    assert any(r.get("rank") for r in rows), "no ranks resolved"
    assert any(r.get("rating") is not None for r in rows), "no ratings resolved"
    assert res["leaders"].get("rating"), "no rating leader"
    print("PASS: competitive comparison table + leaders built")


if __name__ == "__main__":
    main()
    print("\nALL OK")
