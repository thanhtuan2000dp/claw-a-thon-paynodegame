"""Offline tests for UC4 KPI dashboard time filtering.

Tests _apply_trend_filter, _filter_meta, and the UC4 end-to-end
filtering behavior. No network or LLM required.
"""

import datetime
import os
import sys
import types
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usecases.uc4_kpi_dashboard as m

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
    fake_dt = types.SimpleNamespace(
        date=types.SimpleNamespace(today=lambda: datetime.date(2026, 6, 16)),
        timedelta=datetime.timedelta,
    )
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


def test_filter_meta_date_from_only():
    assert _filter_meta(None, "2026-06-01", None) == {
        "type": "range", "date_from": "2026-06-01", "date_to": None
    }


def test_filter_meta_date_to_only():
    assert _filter_meta(None, None, "2026-06-30") == {
        "type": "range", "date_from": None, "date_to": "2026-06-30"
    }


def test_filter_meta_rolling():
    assert _filter_meta(30, None, None) == {"type": "rolling", "window_days": 30}


def test_filter_meta_all():
    assert _filter_meta(None, None, None) == {"type": "all"}


from connectors.base import AppMetadata  # noqa: E402
from storage.snapshots import Snapshot  # noqa: E402
from usecases.uc4_kpi_dashboard import KpiDashboardUseCase  # noqa: E402


def _fake_snap(dates, store="ios"):
    meta = AppMetadata(
        app_id="com.zing.zalo", name="Zalo", store=store,
        version="26.05.02.1", avg_rating=1.95, rating_count=350482,
    )
    history = [
        Snapshot(captured_at=d, app_id="com.zing.zalo", store=store,
                 avg_rating=1.95, rating_count=350000, version="26.05.02.1")
        for d in dates
    ]
    return {"ref": None, "meta": meta, "rank": 6, "rank_chart": "Social Networking", "history": history}


def test_uc4_date_range_filter():
    dates = ["2026-04-15", "2026-05-01", "2026-05-20", "2026-06-01", "2026-06-10"]
    uc = KpiDashboardUseCase()
    with patch("usecases.uc4_kpi_dashboard.snapshot_app", return_value=_fake_snap(dates)):
        result = uc.run({"app": "Zalo", "store": "ios",
                         "date_from": "2026-06-01", "date_to": "2026-06-30"}, deps=None)
    assert result.get("error") is None
    assert result["filter"] == {"type": "range", "date_from": "2026-06-01", "date_to": "2026-06-30"}
    assert len(result["trend"]) == 2
    assert all(r["date"] >= "2026-06-01" for r in result["trend"])


def test_uc4_no_filter_returns_all():
    dates = ["2026-04-15", "2026-05-01", "2026-06-10"]
    uc = KpiDashboardUseCase()
    with patch("usecases.uc4_kpi_dashboard.snapshot_app", return_value=_fake_snap(dates)):
        result = uc.run({"app": "Zalo", "store": "ios"}, deps=None)
    assert result["filter"] == {"type": "all"}
    assert len(result["trend"]) == 3


def test_uc4_window_days_filter():
    import usecases.uc4_kpi_dashboard as uc4_mod
    dates = ["2026-04-15", "2026-05-20", "2026-06-10"]
    fake_dt = types.SimpleNamespace(
        date=types.SimpleNamespace(today=lambda: datetime.date(2026, 6, 16)),
        timedelta=datetime.timedelta,
    )
    uc = KpiDashboardUseCase()
    with patch("usecases.uc4_kpi_dashboard.snapshot_app", return_value=_fake_snap(dates)), \
         patch.object(uc4_mod, "_dt", fake_dt):
        result = uc.run({"app": "Zalo", "store": "ios", "window_days": 45}, deps=None)
    assert result["filter"] == {"type": "rolling", "window_days": 45}
    assert len(result["trend"]) == 2  # 2026-05-20 and 2026-06-10 (cutoff = 2026-05-02)
