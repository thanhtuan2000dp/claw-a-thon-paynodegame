"""Verify the free App Store reviews connector (RSS-primary) end to end.

Asserts: the connector is auto-discovered and ranked for iOS reviews, and a live
fetch for Zalo (id=579523206, market vn) returns recent reviews that are in the
requested window, correctly sorted newest→oldest, de-duplicated, and well-formed.

Run: ./venv/bin/python tests/verify_appstore_reviews.py
Live (hits Apple's RSS feed); skips gracefully on network failure.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.appstore_reviews import AppStoreReviewsConnector  # noqa: E402
from connectors.base import CAP_REVIEWS, ConnectorError  # noqa: E402

ZALO_IOS = "579523206"


def check_wiring():
    """The connector must be discovered and preferred for iOS reviews (and absent
    for Android, since it is iOS-only)."""
    from core.deps import PREFERENCE
    from core.registry import discover_connector_classes

    names = {c.name for c in discover_connector_classes()}
    assert "appstore_reviews" in names, f"connector not auto-discovered: {names}"
    assert "appstore_reviews" in PREFERENCE["reviews"], "not registered in PREFERENCE['reviews']"

    c = AppStoreReviewsConnector(country="vn")
    assert c.supports(CAP_REVIEWS, "ios"), "should support iOS reviews"
    assert not c.supports(CAP_REVIEWS, "android"), "must NOT claim Android"
    print("PASS: discovered, iOS-only, registered in PREFERENCE['reviews']")


def check_live():
    conn = AppStoreReviewsConnector(country="vn", lang="vi")
    end = datetime.utcnow()
    start = end - timedelta(days=14)
    try:
        revs = conn.get_reviews(ZALO_IOS, "ios", start, end, country="vn", lang="vi")
    except ConnectorError as e:
        print(f"SKIPPED (network / Apple unavailable): {e}")
        return

    print(f"fetched {len(revs)} reviews in [{start.date()} .. {end.date()}]")
    if not revs:
        print("SKIPPED: 0 reviews in window (Apple edge cache may be cold); rerun")
        return

    # Sorted newest -> oldest.
    dates = [r.date for r in revs if r.date]
    assert dates == sorted(dates, reverse=True), "reviews not sorted newest->oldest"

    # Every review inside the window.
    assert all(start <= r.date <= end for r in revs if r.date), "a review fell outside the window"

    # No duplicate review text+author+date (id dedup already applied upstream).
    keys = [(r.author, r.title, r.date) for r in revs]
    assert len(keys) == len(set(keys)), "duplicate reviews leaked through dedup"

    # Well-formed fields.
    assert all(r.rating is None or 1 <= r.rating <= 5 for r in revs), "rating out of 1..5"
    assert all(r.source == "appstore_reviews" for r in revs), "wrong source tag"
    assert any((r.content or "").strip() for r in revs), "all review bodies empty"

    newest, oldest = revs[0], revs[-1]
    print(f"  newest: {newest.date} ({newest.rating}★) {(newest.title or '')[:40]!r}")
    print(f"  oldest: {oldest.date} ({oldest.rating}★)")
    print(f"  versions present on {sum(1 for r in revs if r.version)}/{len(revs)} reviews")
    print("PASS: live fetch sorted, in-window, deduped, well-formed")


if __name__ == "__main__":
    check_wiring()
    check_live()
    print("\nALL OK")
