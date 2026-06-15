"""Offline test for the UC7 comparison ordering: rows sort by priority
rank → ratings volume → star rating, with missing values last in each tier."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from usecases.uc7_competitive_comparison import _compare_sort_key  # noqa: E402


def _order(rows):
    return [r["name"] for r in sorted(rows, key=_compare_sort_key)]


def test_rank_then_volume_then_rating():
    rows = [
        {"name": "A", "rank": 2, "ratings_count": 1000, "rating": 4.5},
        {"name": "B", "rank": 1, "ratings_count": 500, "rating": 4.0},
        {"name": "C", "rank": None, "ratings_count": 9999, "rating": 5.0},  # no rank → last tier
        {"name": "D", "rank": 1, "ratings_count": 800, "rating": 4.2},      # ties B on rank, more ratings
    ]
    # rank 1 group ordered by ratings desc (D before B), then rank 2 (A), then no-rank (C)
    assert _order(rows) == ["D", "B", "A", "C"]


def test_volume_then_rating_within_same_rank():
    rows = [
        {"name": "lowstars", "rank": 5, "ratings_count": 300, "rating": 3.0},
        {"name": "tie_morestars", "rank": 5, "ratings_count": 300, "rating": 4.8},  # same vol → higher stars first
        {"name": "morevol", "rank": 5, "ratings_count": 301, "rating": 2.0},        # more volume wins over stars
    ]
    assert _order(rows) == ["morevol", "tie_morestars", "lowstars"]


def test_missing_values_sort_last_in_tier():
    rows = [
        {"name": "has", "rank": 3, "ratings_count": 100, "rating": 4.0},
        {"name": "no_rc", "rank": 3, "ratings_count": None, "rating": 5.0},  # missing ratings_count → after 'has'
    ]
    assert _order(rows) == ["has", "no_rc"]
