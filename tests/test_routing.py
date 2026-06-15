"""Offline tests for the keyword routing fallback (core.router._heuristic_route).

Pure (no network/LLM): intent → action, duration → window_days, platform → store,
filler stripped from the app name. The LLM-first path is covered by live smoke
scripts; this guards the deterministic fallback.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.router import _heuristic_route  # noqa: E402


def test_review_intent_with_window():
    action, params = _heuristic_route("phân tích reviews zalopay 1 tháng gần đây")
    assert action == "uc2_reviews_sentiment"
    assert params["app"] == "zalopay"
    assert params["window_days"] == 30


def test_metadata_intent_with_store():
    action, params = _heuristic_route("thông tin zalo trên app store")
    assert action == "uc1_store_metadata"
    assert params["app"] == "zalo"
    assert params.get("store") == "ios"


def test_default_release_health():
    action, params = _heuristic_route("sức khỏe bản cập nhật zalo")
    assert action == "uc6_version_impact"
    assert params["app"] == "zalo"


def test_hypothesis_marker():
    action, _ = _heuristic_route("tôi nghĩ bản mới làm tăng crash")
    assert action == "hypothesis_check"


def test_duration_parsing():
    assert _heuristic_route("reviews grab 2 tuần qua")[1]["window_days"] == 14
    assert _heuristic_route("reviews grab 1 năm")[1]["window_days"] == 365


def test_package_id_passthrough_and_filler_stripped():
    assert _heuristic_route("review com.zing.zalo")[1]["app"] == "com.zing.zalo"
    # "trở lại / về / ứng dụng" are filler, stripped from the app name
    assert _heuristic_route("phân tích đánh giá về ứng dụng zalo")[1]["app"] == "zalo"
