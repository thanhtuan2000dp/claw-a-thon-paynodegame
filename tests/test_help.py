"""Offline tests for the greeting/help intent: the router's _looks_like_help
detector, the HelpUseCase payload (capabilities + suggestions, VI/EN), and that
Router.handle short-circuits a greeting to `help` with no LLM call."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.deps import Deps  # noqa: E402
from core.router import Router, _looks_like_help  # noqa: E402
from storage.snapshots import SnapshotStore  # noqa: E402
from storage.subscriptions import SubscriptionStore  # noqa: E402
from usecases.help import HelpUseCase  # noqa: E402


def test_looks_like_help_positives():
    for m in ["xin chào", "Chào bạn!", "hello", "Hi!", "hey there", "/start",
              "bạn làm được gì?", "agent làm được những gì", "giúp được gì",
              "what can you do?", "who are you", "help", "hướng dẫn", "dùng thế nào"]:
        assert _looks_like_help(m), m


def test_looks_like_help_negatives():
    for m in ["phân tích review gần đây của Zalo", "so sánh ZaloPay với đối thủ",
              "tôi nghĩ rating giảm do bản cập nhật mới", "rating của TikTok 3 tháng qua",
              "com.zing.zalo", "MoMo có bất thường gì không"]:
        assert not _looks_like_help(m), m


def test_help_usecase_payload_vi_and_en():
    vi = HelpUseCase().run({"lang": "vi"}, deps=None)
    assert vi["use_case"] == "help" and vi["lang"] == "vi"
    assert vi["capabilities"] and vi["suggestions"]
    assert any("Zalo" in s for s in vi["suggestions"])

    en = HelpUseCase().run({"lang": "en"}, deps=None)
    assert en["suggestions"] != vi["suggestions"]
    assert any("Instagram" in s for s in en["suggestions"])


def _deps():
    return Deps(connectors=[], storage=SnapshotStore(tempfile.mkdtemp()),
                subscriptions=SubscriptionStore(tempfile.mkdtemp()))


def test_router_greeting_short_circuits_to_help():
    # No LLM is configured here; a greeting must still resolve to `help` via the
    # fast-path (not an analysis, not an LLM call).
    r = Router(_deps())
    res = r.handle({"message": "xin chào"}, None)
    assert res["use_case"] == "help"
    assert res["suggestions"]


def test_router_help_question_short_circuits():
    r = Router(_deps())
    res = r.handle({"message": "bạn làm được gì?"}, None)
    assert res["use_case"] == "help"
