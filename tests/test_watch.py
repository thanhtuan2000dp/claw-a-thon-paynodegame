"""Offline tests for the UC9 anomaly watch (no network): notifier selection +
dry-run, Telegram send via an injected transport, message formatting, watchlist
parsing, and a full cycle driven by a fake connector + seeded snapshot."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.base import CAP_METADATA, AppDataConnector, AppMetadata  # noqa: E402
from core.alerts import (  # noqa: E402
    DryRunNotifier,
    TelegramNotifier,
    format_uc9_alert,
    make_notifier,
)
from core.deps import Deps  # noqa: E402
from scheduler.watch import load_watchlist, run_watch_cycle  # noqa: E402
from storage.snapshots import Snapshot, SnapshotStore  # noqa: E402


# --- notifier selection ------------------------------------------------------
def test_make_notifier_dry_run_when_unconfigured():
    n = make_notifier({})
    assert isinstance(n, DryRunNotifier)
    assert "TELEGRAM_BOT_TOKEN" in n.reason and "TELEGRAM_CHAT_ID" in n.reason


def test_make_notifier_telegram_when_configured():
    n = make_notifier({"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"})
    assert isinstance(n, TelegramNotifier)


# --- telegram transport ------------------------------------------------------
def test_telegram_sends_via_injected_transport():
    calls = []
    n = TelegramNotifier("TOK", "CHAT", transport=lambda url, payload: calls.append((url, payload)))
    out = n.send("hi")
    assert out == {"channel": "telegram", "status": "sent"}
    assert "botTOK/sendMessage" in calls[0][0]
    assert calls[0][1]["chat_id"] == "CHAT" and calls[0][1]["text"] == "hi"


def test_telegram_error_is_caught_not_raised():
    def boom(url, payload):
        raise RuntimeError("network down")

    out = TelegramNotifier("T", "C", transport=boom).send("x")
    assert out["status"] == "error" and "network down" in out["error"]


# --- message formatting ------------------------------------------------------
def test_format_single_alert():
    res = {"status": "alert", "lang": "vi", "app": {"name": "Zalo", "store": "ios"},
           "baseline_date": "2026-06-01",
           "alerts": [{"type": "rating_drop", "severity": "high", "message": "Rating giảm -0.30"}]}
    msg = format_uc9_alert(res)
    assert "Zalo (ios)" in msg and "Rating giảm -0.30" in msg and "🔴" in msg


def test_format_no_alert_returns_none():
    assert format_uc9_alert({"status": "baseline_seeded", "alerts": []}) is None
    assert format_uc9_alert({"status": "ok", "alerts": []}) is None


def test_format_cross_platform_only_alerting_stores():
    res = {"mode": "cross_platform", "lang": "en", "app_query": "Zalo",
           "platforms": {
               "ios": {"status": "alert", "app": {"name": "Zalo", "store": "ios"},
                       "alerts": [{"severity": "medium", "message": "rank slid 5"}]},
               "android": {"status": "ok", "alerts": []}}}
    msg = format_uc9_alert(res)
    assert "anomalies detected" in msg and "Zalo (ios)" in msg and "rank slid 5" in msg
    assert "android" not in msg  # the OK platform is omitted


# --- watchlist parsing -------------------------------------------------------
def test_load_watchlist_shorthand():
    wl = load_watchlist({"ALERT_WATCHLIST": "Zalo|both|vi, 284882215|ios"})
    assert wl[0] == {"app": "Zalo", "store": "both", "lang": "vi"}
    assert wl[1] == {"app": "284882215", "store": "ios"}


def test_load_watchlist_empty_when_unset():
    assert load_watchlist({}) == []


# --- full cycle (real UC9 + fake connector) ----------------------------------
class FakeMeta(AppDataConnector):
    name = "fakemeta"
    stores = {"ios"}

    def capabilities(self):
        return {CAP_METADATA}

    def get_metadata(self, app_id, store="ios", country=None, lang=None):
        return AppMetadata(app_id=app_id, name="FakeApp", store="ios",
                           version="2.0", avg_rating=1.95, rating_count=350000)


def test_watch_cycle_delivers_on_alert():
    st = SnapshotStore(tempfile.mkdtemp())
    st.save(Snapshot(captured_at="2026-06-01", app_id="999", store="ios",
                     version="1.0", avg_rating=2.5, rating_count=349000, rank=None))
    notifier = DryRunNotifier()
    report = run_watch_cycle(Deps(connectors=[FakeMeta()], storage=st), notifier,
                             [{"app": "999", "store": "ios", "lang": "vi"}])
    assert report["alerted"] == 1
    assert report["results"][0]["uc_status"] == "alert"
    assert len(notifier.sent) == 1 and "Rating" in notifier.sent[0]


def test_watch_cycle_no_delivery_on_baseline():
    st = SnapshotStore(tempfile.mkdtemp())
    notifier = DryRunNotifier()
    report = run_watch_cycle(Deps(connectors=[FakeMeta()], storage=st), notifier,
                             [{"app": "999", "store": "ios", "lang": "vi"}])
    assert report["alerted"] == 0
    assert report["results"][0]["delivery"]["status"] == "no_alert"
    assert notifier.sent == []
