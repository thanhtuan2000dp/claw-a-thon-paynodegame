"""Offline tests for UC2's deterministic statistics (no network/LLM): the star
distribution and sentiment split each reconcile to the rated total, and weekly
volumes sum to the review count."""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.base import Review  # noqa: E402
from usecases.uc2_reviews_sentiment import ReviewsSentimentUseCase  # noqa: E402


def _r(rating, day, content="ổn"):
    return Review(content=content, rating=rating, date=datetime(2026, 6, day), source="x")


def test_statistics_reconcile():
    reviews = [_r(5, 1), _r(5, 2), _r(4, 3), _r(3, 8), _r(2, 9), _r(1, 10), _r(1, 11, "tệ")]
    s = ReviewsSentimentUseCase()._statistics(reviews)

    rated = s["totals"]["rated"]
    assert rated == 7
    assert sum(s["star_distribution"][k]["count"] for k in s["star_distribution"]) == rated
    senti = s["sentiment"]
    assert senti["negative"]["count"] + senti["neutral"]["count"] + senti["positive"]["count"] == rated
    # negatives = 1-2★ (3 of them), neutral = 3★ (1), positive = 4-5★ (3)
    assert senti["negative"]["count"] == 3
    assert senti["neutral"]["count"] == 1
    assert senti["positive"]["count"] == 3
    assert sum(w["volume"] for w in s["weekly_trend"]) == len(reviews)
    assert s["avg_rating"] is not None


def test_empty_reviews():
    s = ReviewsSentimentUseCase()._statistics([])
    assert s["totals"]["rated"] == 0
    assert s["avg_rating"] is None
