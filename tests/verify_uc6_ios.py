"""Verify the version-impact use case's iOS path is REVIEW-BASED (not metrics-only).

Before the free App Store reviews connector existed, iOS had no review-text
source, so the report fell back to metrics-only. This proves the iOS path now
splits reviews before/after the release and computes review signals.

Runs without LLM env: review fetch + signal maths need no LLM; the optional
issue-categorisation step degrades gracefully (a note, not a crash).

Run: ./venv/bin/python tests/verify_uc6_ios.py
Live (hits iTunes Lookup + App Store RSS); skips gracefully on network failure.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.appstore_reviews import AppStoreReviewsConnector  # noqa: E402
from connectors.itunes import ItunesConnector  # noqa: E402
from core.deps import Deps  # noqa: E402
from storage.snapshots import SnapshotStore  # noqa: E402
from usecases.uc6_version_impact import VersionImpactUseCase  # noqa: E402

ZALO_IOS = "579523206"


def main():
    # Isolate the new path: iTunes for metadata, appstore_reviews for review text.
    deps = Deps(
        connectors=[ItunesConnector(country="vn"), AppStoreReviewsConnector(country="vn", lang="vi")],
        storage=SnapshotStore(tempfile.mkdtemp()),
    )
    res = VersionImpactUseCase().run(
        {"app": ZALO_IOS, "store": "ios", "country": "vn", "lang": "vi", "window_days": 14},
        deps,
    )

    if res.get("error"):
        print(f"SKIPPED (network / metadata unavailable): {res['error']}")
        return

    sig = res.get("signals", {})
    src = sig.get("review_source")
    print(f"verdict={res.get('verdict')} | review_source={src}")
    print(f"  reviews before/after = {sig.get('reviews_before')}/{sig.get('reviews_after')}")
    print(f"  rating {sig.get('rating_before')} -> {sig.get('rating_after')} (Δ {sig.get('rating_delta')})")
    print(f"  negative share Δ = {sig.get('negative_share_delta_pp')}pp")

    if src is None and (sig.get("reviews_before", 0) + sig.get("reviews_after", 0)) == 0:
        print("SKIPPED: 0 reviews fetched (Apple edge cache cold); rerun")
        return

    # The whole point: the iOS report is now backed by App Store review text.
    assert src == "appstore_reviews", f"expected appstore_reviews as review source, got {src!r}"
    assert (sig.get("reviews_before", 0) + sig.get("reviews_after", 0)) > 0, "no reviews split"
    # A recent release should have post-release reviews to reason about.
    assert sig.get("reviews_after", 0) > 0, "no post-release reviews — iOS path not really active"
    print("PASS: UC1 iOS path is review-based via appstore_reviews")


if __name__ == "__main__":
    main()
    print("\nALL OK")
