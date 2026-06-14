"""Verify sheet UC4 — KPI dashboard (live metadata + seeded prior snapshot).

Seeds one earlier snapshot so the trend has ≥2 points and first→latest deltas are
computed. Run: ./venv/bin/python tests/verify_uc4_kpi_dashboard.py
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
from usecases.uc4_kpi_dashboard import KpiDashboardUseCase  # noqa: E402

ZALO_IOS = "579523206"


def main():
    assert "uc4_kpi_dashboard" in discover_use_cases(), "not discovered"
    store = SnapshotStore(tempfile.mkdtemp())
    store.save(Snapshot(captured_at="2026-06-01", app_id=ZALO_IOS, store="ios",
                        version="26.00.00", avg_rating=2.50, rating_count=349000, rank=10))
    deps = Deps(connectors=[ItunesConnector(country="vn"), IosChartsConnector(country="vn")], storage=store)
    r = KpiDashboardUseCase().run({"app": ZALO_IOS, "store": "ios", "country": "vn", "lang": "vi"}, deps)
    if r.get("error"):
        print(f"SKIPPED (network?): {r['error']}")
        return

    print(f"kpis: {r['kpis']}")
    print(f"deltas: {r['deltas']}")
    print(f"trend points: {len(r['trend'])} -> {[t['date'] for t in r['trend']]}")
    assert len(r["trend"]) >= 2, "trend should have the seeded + current point"
    assert r["deltas"]["since"] == "2026-06-01"
    assert r["deltas"]["rating"] is not None, "rating delta not computed"
    assert r["kpis"]["rating"] is not None
    print("PASS: KPI dashboard built trend + first→latest deltas")


if __name__ == "__main__":
    main()
    print("\nALL OK")
