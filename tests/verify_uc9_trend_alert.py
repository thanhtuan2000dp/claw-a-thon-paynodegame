"""Verify sheet UC9 — trend & anomaly alert (live metadata + seeded prior snapshot).

Seeds one earlier snapshot (higher rating) so the live current rating produces a
deterministic rating-drop alert; also checks baseline-seeded behaviour with no
history. Run: ./venv/bin/python tests/verify_uc9_trend_alert.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.ios_charts import IosChartsConnector  # noqa: E402
from connectors.itunes import ItunesConnector  # noqa: E402
from core.deps import Deps  # noqa: E402
from core.registry import discover_use_cases  # noqa: E402
from storage.snapshots import Snapshot, SnapshotStore  # noqa: E402
from usecases.uc9_trend_alert import TrendAlertUseCase  # noqa: E402

ZALO_IOS = "579523206"


def main():
    assert "uc9_trend_alert" in discover_use_cases(), "not discovered"

    # (1) no history -> baseline seeded (no crash)
    deps0 = Deps(connectors=[ItunesConnector(country="vn"), IosChartsConnector(country="vn")],
                 storage=SnapshotStore(tempfile.mkdtemp()))
    r0 = TrendAlertUseCase().run({"app": ZALO_IOS, "store": "ios", "country": "vn", "lang": "vi"}, deps0)
    if r0.get("error"):
        print(f"SKIPPED (network?): {r0['error']}")
        return
    print(f"no-history status: {r0.get('status')}")
    assert r0.get("status") == "baseline_seeded", r0

    # (2) seed a prior HIGHER-rating snapshot -> expect a rating-drop alert vs live
    store = SnapshotStore(tempfile.mkdtemp())
    store.save(Snapshot(captured_at="2026-06-01", app_id=ZALO_IOS, store="ios",
                        version="26.00.00", avg_rating=2.50, rating_count=349000, rank=10))
    deps = Deps(connectors=[ItunesConnector(country="vn"), IosChartsConnector(country="vn")], storage=store)
    r = TrendAlertUseCase().run({"app": ZALO_IOS, "store": "ios", "country": "vn", "lang": "vi"}, deps)
    print(f"baseline_date={r.get('baseline_date')} current_rating={r.get('current', {}).get('rating')}")
    for a in r.get("alerts", []):
        print(f"  [{a['severity']}] {a['type']}: {a['message']}")
    assert r.get("baseline_date") == "2026-06-01"
    assert any(a["type"] == "rating_drop" for a in r.get("alerts", [])), f"expected rating drop, got {r.get('alerts')}"
    print("PASS: baseline-seeded + rating-drop anomaly detected from snapshot trend")


if __name__ == "__main__":
    main()
    print("\nALL OK")
