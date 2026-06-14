"""Sheet UC6 (version impact / post-release health) tests.

  • test_signals_synthetic  — deterministic analytics check with a fake connector
                              (no network, no LLM). Asserts before/after split,
                              rating delta, negative-share, and verdict.
  • live_itunes             — runs the use case against the real iTunes API for a
                              chosen app and prints the report (manual smoke test).

Run:
  ./venv/bin/python tests/test_uc6_version_impact.py            # synthetic + live iTunes
  ./venv/bin/python tests/test_uc6_version_impact.py --no-live  # synthetic asserts only
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.base import (  # noqa: E402
    CAP_METADATA,
    CAP_REVIEWS,
    CAP_SEARCH,
    AppDataConnector,
    AppMetadata,
    AppRef,
    Review,
)
from core.deps import Deps  # noqa: E402
from outputs.markdown import MarkdownOutput  # noqa: E402
from storage.snapshots import Snapshot, SnapshotStore  # noqa: E402
from usecases.uc6_version_impact import VersionImpactUseCase  # noqa: E402

RELEASE = datetime(2026, 6, 1, tzinfo=timezone.utc)


class FakeConnector(AppDataConnector):
    name = "fake"
    stores = {"ios", "android"}

    def capabilities(self):
        return {CAP_SEARCH, CAP_METADATA, CAP_REVIEWS}

    def search_app(self, term, store, country=None, lang=None):
        return [AppRef(app_id="123", name="FakeApp", store=store)]

    def get_metadata(self, app_id, store, country=None, lang=None):
        return AppMetadata(
            app_id="123",
            name="FakeApp",
            store=store,
            version="2.0.0",
            avg_rating=3.5,
            rating_count=1000,
            current_version_release_date=RELEASE,
        )

    def get_reviews(self, app_id, store, start_date, end_date, country=None, lang=None):
        return _fake_reviews()


def _fake_reviews():
    def r(rating, month, day, text):
        return Review(
            content=text,
            rating=rating,
            date=datetime(2026, month, day, tzinfo=timezone.utc),
            source="fake",
        )

    before = [r(5, 5, 20, "love it"), r(5, 5, 25, "great"), r(4, 5, 28, "good")]
    after = [
        r(2, 6, 2, "crashes on launch after update"),
        r(1, 6, 3, "cannot log in anymore"),
        r(3, 6, 4, "laggy now"),
        r(2, 6, 5, "keeps crashing"),
        r(5, 6, 6, "still fine for me"),
        r(4, 6, 7, "ok"),
    ]
    return before + after


def _build_deps():
    storage = SnapshotStore(base_dir="/tmp/uc1_test_snapshots")
    return Deps(
        connectors=[FakeConnector()],
        storage=storage,
        config={"default_store": "ios", "default_country": "us"},
    )


def test_signals_synthetic():
    uc = VersionImpactUseCase()
    result = uc.run({"app": "FakeApp", "store": "ios", "window_days": 14}, _build_deps())

    sig = result["signals"]
    assert result["app"]["name"] == "FakeApp", result
    assert sig["reviews_before"] == 3, sig
    assert sig["reviews_after"] == 6, sig
    # before avg = (5+5+4)/3 = 4.67 ; after avg = (2+1+3+2+5+4)/6 = 2.83
    assert sig["rating_before"] == 4.67, sig
    assert sig["rating_after"] == 2.83, sig
    assert sig["rating_delta"] < -1.5, sig
    # negative share: before 0%, after 3/6 = 50%
    assert sig["negative_share_before"] == 0.0, sig
    assert sig["negative_share_after"] == 50.0, sig
    assert result["verdict"] == "regression", result
    print("✅ test_signals_synthetic passed")
    print("   verdict:", result["verdict"], "| rating", sig["rating_before"], "→", sig["rating_after"])
    print(MarkdownOutput().render(result))


class MetaOnlyConnector(AppDataConnector):
    """Simulates iOS: metadata + search, but NO reviews (like iTunes)."""

    name = "metaonly"
    stores = {"ios"}

    def capabilities(self):
        return {CAP_SEARCH, CAP_METADATA}

    def search_app(self, term, store, country=None, lang=None):
        return [AppRef(app_id="999", name="MetaApp", store=store)]

    def get_metadata(self, app_id, store, country=None, lang=None):
        return AppMetadata(
            app_id="999",
            name="MetaApp",
            store=store,
            version="3.0",
            avg_rating=4.30,
            rating_count=10000,
            current_version_release_date=RELEASE,
        )


def test_metric_trend_synthetic():
    """iOS metrics-only path: snapshot history yields a rating trend + verdict."""
    import shutil

    shutil.rmtree("/tmp/uc1_metric_test", ignore_errors=True)
    storage = SnapshotStore(base_dir="/tmp/uc1_metric_test")
    # Seed a prior snapshot: rating 4.50 -> current 4.30 => Δ -0.20 (regression).
    storage.save(
        Snapshot(captured_at="2026-06-10", app_id="999", store="ios", version="2.9",
                 avg_rating=4.50, rating_count=9000)
    )
    deps = Deps(
        connectors=[MetaOnlyConnector()],
        storage=storage,
        config={"default_store": "ios", "default_country": "us"},
    )
    res = VersionImpactUseCase().run({"app": "MetaApp", "store": "ios"}, deps)
    sig = res["signals"]
    assert sig["review_source"] is None, sig
    assert sig["metric_rating_delta"] == -0.2, sig
    assert sig["new_ratings_since_baseline"] == 1000, sig
    assert res["verdict"] == "regression", res
    print(
        "✅ test_metric_trend_synthetic passed "
        f"(verdict: {res['verdict']}, metric Δ: {sig['metric_rating_delta']}, "
        f"+{sig['new_ratings_since_baseline']} ratings)"
    )


def live_itunes(app_name: str = "Instagram"):
    from connectors.itunes import ItunesConnector

    storage = SnapshotStore(base_dir="/tmp/uc1_live_snapshots")
    deps = Deps(
        connectors=[ItunesConnector(country="us")],
        storage=storage,
        config={"default_store": "ios", "default_country": "us"},
    )
    uc = VersionImpactUseCase()
    result = uc.run({"app": app_name, "store": "ios"}, deps)
    print("\n=== LIVE iTunes:", app_name, "===")
    print("app:", result.get("app"))
    print("release:", result.get("release"))
    print("verdict:", result.get("verdict"))
    print("notes:", result.get("notes"))
    print("\n--- markdown ---")
    print(MarkdownOutput().render(result))


def live_googleplay(package: str = "com.instagram.android"):
    """Full review pipeline against live Google Play (Android).

    Note: for very high-volume apps, the newest N reviews may all post-date the
    release, leaving an empty 'before' bucket -> inconclusive delta (after-state
    still reported). Date-bounded Sensor Tower queries solve this.
    """
    from connectors.googleplay import GooglePlayConnector

    deps = Deps(
        connectors=[GooglePlayConnector(country="us", lang="en", review_count=200)],
        storage=SnapshotStore(base_dir="/tmp/uc1_gp_snapshots"),
        config={"default_store": "android", "default_country": "us"},
    )
    result = VersionImpactUseCase().run(
        {"app": package, "store": "android", "window_days": 14}, deps
    )
    sig = result["signals"]
    print("\n=== LIVE Google Play:", package, "===")
    print("app:", result["app"]["name"], "| verdict:", result["verdict"])
    print(
        "reviews before/after:",
        sig["reviews_before"],
        "/",
        sig["reviews_after"],
        "| source:",
        sig["review_source"],
    )
    print("rating after:", sig["rating_after"], "| neg share after:", sig["negative_share_after"])


if __name__ == "__main__":
    test_signals_synthetic()
    test_metric_trend_synthetic()
    if "--no-live" not in sys.argv:
        for label, fn in (("iTunes", lambda: live_itunes("Spotify")), ("GooglePlay", live_googleplay)):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                print(f"(live {label} test skipped: {exc})")
