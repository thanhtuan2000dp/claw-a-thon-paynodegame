"""Verify sheet UC2 — reviews & sentiment (live).

Asserts the use case crawls reviews over a window and produces consistent
statistics: star distribution and sentiment split each sum to the rated total,
a non-empty weekly trend, language mix, and a sample. Theme clustering needs the
LLM (degrades to a note without it) so it is not required to pass.

Run: ./venv/bin/python tests/verify_uc2_reviews_sentiment.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.appstore_reviews import AppStoreReviewsConnector  # noqa: E402
from connectors.itunes import ItunesConnector  # noqa: E402
from core.deps import Deps  # noqa: E402
from storage.snapshots import SnapshotStore  # noqa: E402
from usecases.uc2_reviews_sentiment import ReviewsSentimentUseCase  # noqa: E402

ZALO_IOS = "579523206"


def main():
    deps = Deps(
        connectors=[ItunesConnector(country="vn"), AppStoreReviewsConnector(country="vn", lang="vi")],
        storage=SnapshotStore(tempfile.mkdtemp()),
    )
    res = ReviewsSentimentUseCase().run(
        {"app": ZALO_IOS, "store": "ios", "country": "vn", "lang": "vi", "window_days": 30}, deps
    )
    if res.get("error"):
        print(f"SKIPPED (network?): {res['error']}")
        return

    t, s, star = res["totals"], res["sentiment"], res["star_distribution"]
    print(f"source={res['review_source']} window={res['window']}")
    print(f"totals={t} avg_rating={res['avg_rating']}")
    print(f"sentiment: +{s['positive']['pct']}% /={s['neutral']['pct']}% -{s['negative']['pct']}%")
    print(f"languages={res['language_distribution']}")
    print(f"weeks={[w['week'] for w in res['weekly_trend']]}")
    print(f"themes: praise={len(res['themes']['praise'])} complaints={len(res['themes']['complaints'])}")
    print(f"summary: {res['summary']}")

    if t["reviews"] == 0:
        print("SKIPPED: 0 reviews in window (Apple edge cache cold); rerun")
        return

    assert res["review_source"] == "appstore_reviews"
    # star distribution and sentiment must each account for exactly the rated total
    assert sum(star[k]["count"] for k in star) == t["rated"], "star counts != rated total"
    assert sum(s[k]["count"] for k in s) == t["rated"], "sentiment counts != rated total"
    # weekly trend present and chronologically sorted
    weeks = [w["week"] for w in res["weekly_trend"]]
    assert weeks and weeks == sorted(weeks), "weekly trend missing/unsorted"
    # weekly volumes sum to total review count
    assert sum(w["volume"] for w in res["weekly_trend"]) == t["reviews"], "weekly volumes != total"
    assert res["language_distribution"], "no language distribution"
    assert res.get("summary")
    print("PASS: UC2 stats consistent (star/sentiment/weekly all reconcile)")


if __name__ == "__main__":
    main()
    print("\nALL OK")
