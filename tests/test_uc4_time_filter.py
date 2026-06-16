"""Offline tests for UC4 KPI dashboard time filtering.

Tests _apply_trend_filter, _filter_meta, and the UC4 end-to-end
filtering behavior. No network or LLM required.
"""

import datetime
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from usecases.uc4_kpi_dashboard import _apply_trend_filter, _filter_meta  # noqa: E402

TREND = [
    {"date": "2026-04-15", "rating": 4.0, "rank": 10, "ratings_count": 1000, "version": "1.0"},
    {"date": "2026-05-01", "rating": 3.8, "rank": 12, "ratings_count": 1050, "version": "1.1"},
    {"date": "2026-05-20", "rating": 3.6, "rank": 15, "ratings_count": 1100, "version": "1.1"},
    {"date": "2026-06-01", "rating": 3.5, "rank": 14, "ratings_count": 1150, "version": "1.2"},
    {"date": "2026-06-10", "rating": 3.4, "rank": 13, "ratings_count": 1200, "version": "1.2"},
]


def test_filter_no_params_returns_all():
    assert _apply_trend_filter(TREND, None, None, None) == TREND


def test_filter_date_range():
    result = _apply_trend_filter(TREND, None, "2026-05-01", "2026-05-31")
    assert [r["date"] for r in result] == ["2026-05-01", "2026-05-20"]


def test_filter_date_from_only():
    result = _apply_trend_filter(TREND, None, "2026-06-01", None)
    assert [r["date"] for r in result] == ["2026-06-01", "2026-06-10"]


def test_filter_date_to_only():
    result = _apply_trend_filter(TREND, None, None, "2026-04-30")
    assert [r["date"] for r in result] == ["2026-04-15"]


def test_filter_window_days():
    # Mock today as 2026-06-16 → cutoff = 2026-05-02 (45 days back)
    import usecases.uc4_kpi_dashboard as m
    FakeDate = type("FakeDate", (), {"today": staticmethod(lambda: datetime.date(2026, 6, 16))})
    fake_dt = type("FakeDt", (), {"date": FakeDate, "timedelta": datetime.timedelta})()
    with patch.object(m, "_dt", fake_dt):
        result = _apply_trend_filter(TREND, 45, None, None)
    assert [r["date"] for r in result] == ["2026-05-20", "2026-06-01", "2026-06-10"]


def test_filter_date_range_takes_priority_over_window_days():
    # date_from/date_to wins even when window_days is also present
    result = _apply_trend_filter(TREND, 7, "2026-05-01", "2026-05-31")
    assert [r["date"] for r in result] == ["2026-05-01", "2026-05-20"]


def test_filter_meta_range():
    assert _filter_meta(None, "2026-06-01", "2026-06-16") == {
        "type": "range", "date_from": "2026-06-01", "date_to": "2026-06-16"
    }


def test_filter_meta_rolling():
    assert _filter_meta(30, None, None) == {"type": "rolling", "window_days": 30}


def test_filter_meta_all():
    assert _filter_meta(None, None, None) == {"type": "all"}
