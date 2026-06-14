"""Verify Google Play resolves an app whose best match arrives as a null-id
featured result (the appId-recovery path).

Regression guard for the ZaloPay bug: searching "zalopay" used to drop the
null-id consumer app and pick "ZaloPay Merchant" instead.

Run: ./venv/bin/python tests/verify_googleplay_resolve.py
Live (hits Google Play); skips gracefully if the library/network is unavailable.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.base import ConnectorError  # noqa: E402
from connectors.googleplay import GooglePlayConnector  # noqa: E402


def main():
    gp = GooglePlayConnector(country="vn", lang="vi")
    if not gp.is_available():
        print("SKIPPED: google-play-scraper not importable")
        return
    try:
        refs = gp.search_app("zalopay", "android")
    except ConnectorError as e:
        print(f"SKIPPED (network?): {e}")
        return

    assert refs, "no results for 'zalopay'"
    top = refs[0]
    print(f"top match: {top.name!r} | {top.app_id}")

    # The consumer app must win over the Merchant variant.
    assert top.app_id == "vn.com.vng.zalopay", (
        f"expected consumer package, got {top.app_id!r}"
    )
    assert "merchant" not in top.app_id.lower()

    # No duplicate package ids in the result set.
    ids = [r.app_id for r in refs]
    assert len(ids) == len(set(ids)), f"duplicate app_ids: {ids}"

    print("PASS: null-id featured result recovered; consumer ZaloPay resolved")


if __name__ == "__main__":
    main()
    print("\nALL OK")
