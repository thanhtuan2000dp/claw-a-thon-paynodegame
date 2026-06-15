"""Verify sheet UC3 — version changelog timeline.

Two checks:
  1) Offline: seed snapshots spanning two versions (with notes) and assert the
     timeline collapses them into 2 entries, newest-first, with notes attached.
  2) Live: run against a real app (one version observed on the first run) and
     assert the timeline + summary build. Highlights need the LLM (degrade to a
     note), so they are not required to pass.

Run: ./venv/bin/python tests/verify_uc3_version_changelog.py
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
from usecases.uc3_version_changelog import VersionChangelogUseCase  # noqa: E402

ZALO_IOS = "1112407590"


def test_timeline_collapse():
    """Pure logic: 3 days, 2 versions -> 2 entries, newest first, notes carried."""
    tl = VersionChangelogUseCase._timeline([
        Snapshot(captured_at="2026-06-01", app_id="x", store="ios", version="1.0",
                 release_notes="initial release", current_version_release_date="2026-05-30"),
        Snapshot(captured_at="2026-06-02", app_id="x", store="ios", version="1.0",
                 release_notes="initial release"),
        Snapshot(captured_at="2026-06-03", app_id="x", store="ios", version="1.1",
                 release_notes="dark mode + bug fixes", current_version_release_date="2026-06-03"),
    ])
    assert len(tl) == 2, f"expected 2 versions, got {len(tl)}"
    assert tl[0]["version"] == "1.1", "newest version must be first"
    assert tl[1]["version"] == "1.0"
    assert tl[1]["first_seen"] == "2026-06-01" and tl[1]["last_seen"] == "2026-06-02", "v1.0 span wrong"
    assert "dark mode" in tl[0]["release_notes"]
    assert tl[0]["release_date"] == "2026-06-03"
    print("PASS: timeline collapses snapshots into per-version entries (newest first)")


def test_live():
    deps = Deps(
        connectors=[ItunesConnector(country="vn"), IosChartsConnector(country="vn")],
        storage=SnapshotStore(tempfile.mkdtemp()),
    )
    res = VersionChangelogUseCase().run(
        {"app": ZALO_IOS, "store": "ios", "country": "vn", "lang": "vi"}, deps
    )
    if res.get("error"):
        print(f"SKIPPED live (network?): {res['error']}")
        return
    print(f"\napp: {res['app']['name']} | current: v{res.get('current_version')}")
    for v in res["versions"]:
        print(f"  v{v['version']:12} first_seen={v['first_seen']} release_date={v.get('release_date')}")
        if v.get("release_notes"):
            print(f"      notes: {v['release_notes'][:90]}")
    print(f"summary: {res['summary']}")
    print(f"highlights (LLM): {len(res.get('highlights', []))} | notes: {[n for n in res['notes'] if n]}")

    assert res["versions"], "expected at least one observed version"
    assert res["versions"][0]["version"], "version row missing version"
    assert res.get("current_version"), "current_version missing"
    # The just-saved live snapshot should carry the current version's notes for free.
    assert res["versions"][0].get("release_notes"), "live snapshot did not capture release notes"
    print("PASS: live version timeline built with current-version notes captured")


def main():
    assert "uc3_version_changelog" in discover_use_cases(), "use case not auto-discovered"
    test_timeline_collapse()
    test_live()


if __name__ == "__main__":
    main()
    print("\nALL OK")
