"""Offline tests for per-user alert subscriptions (no network): the store
round-trip, schedule due-matching + last_sent guard, the manage_subscription use
case (create/cap/list/delete/test), per-recipient Telegram send, and a full
subscription cycle that delivers to the sub's own chat_id and won't re-fire."""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.base import CAP_METADATA, AppDataConnector, AppMetadata  # noqa: E402
from core.alerts import DryRunNotifier, TelegramNotifier  # noqa: E402
from core.deps import Deps  # noqa: E402
from scheduler.watch import _is_due, due_subscriptions, run_subscription_cycle  # noqa: E402
from storage.snapshots import Snapshot, SnapshotStore  # noqa: E402
from storage.subscriptions import Subscription, SubscriptionStore  # noqa: E402
from usecases.manage_subscription import ManageSubscriptionUseCase  # noqa: E402


def _store():
    return SubscriptionStore(tempfile.mkdtemp())


# --- store round-trip --------------------------------------------------------
def test_store_add_list_get_delete():
    st = _store()
    a = st.add(Subscription(chat_id="C1", app="zalo", store="ios"))
    st.add(Subscription(chat_id="C2", app="spotify", store="android"))
    assert st.count() == 2 and st.count("C1") == 1
    assert {s.app for s in st.list("C1")} == {"zalo"}
    assert st.get(a.id).app == "zalo"
    assert st.delete(a.id, chat_id="WRONG") is False  # chat must match
    assert st.delete(a.id, chat_id="C1") is True
    assert st.get(a.id) is None and st.count() == 1


def test_store_mark_sent_and_active():
    st = _store()
    a = st.add(Subscription(chat_id="C1", app="zalo", active=True))
    st.add(Subscription(chat_id="C1", app="x", active=False))
    assert len(st.all_active()) == 1
    st.mark_sent(a.id, "2026-06-15")
    assert st.get(a.id).last_sent == "2026-06-15"


# --- schedule matching -------------------------------------------------------
def test_is_due_daily_hour_and_guard():
    now = datetime(2026, 6, 15, 9, 0, 0)
    due = Subscription(chat_id="C", app="a", freq="daily", hour=9)
    assert _is_due(due, now) is True
    assert _is_due(Subscription(chat_id="C", app="a", freq="daily", hour=10), now) is False
    already = Subscription(chat_id="C", app="a", freq="daily", hour=9, last_sent="2026-06-15")
    assert _is_due(already, now) is False
    assert _is_due(Subscription(chat_id="C", app="a", freq="daily", hour=9, active=False), now) is False


def test_is_due_weekly_weekday():
    now = datetime(2026, 6, 15, 9, 0, 0)
    wd = now.weekday()
    assert _is_due(Subscription(chat_id="C", app="a", freq="weekly", hour=9, weekday=wd), now) is True
    assert _is_due(Subscription(chat_id="C", app="a", freq="weekly", hour=9, weekday=(wd + 1) % 7), now) is False


# --- manage_subscription use case --------------------------------------------
def _deps_with_subs(subs=None):
    return Deps(connectors=[], storage=SnapshotStore(tempfile.mkdtemp()),
                subscriptions=subs or _store())


def test_usecase_create_and_list():
    deps = _deps_with_subs()
    uc = ManageSubscriptionUseCase()
    r = uc.run({"op": "create", "chat_id": "C1", "app": "zalopay", "store": "ios",
                "freq": "daily", "hour": "8", "lang": "vi"}, deps)
    assert r["status"] == "success" and r["subscription"]["hour"] == 8
    listed = uc.run({"op": "list", "chat_id": "C1"}, deps)
    assert len(listed["subscriptions"]) == 1


def test_usecase_requires_chat_and_app():
    deps = _deps_with_subs()
    uc = ManageSubscriptionUseCase()
    assert uc.run({"op": "create", "app": "x"}, deps)["status"] == "error"          # no chat_id
    assert uc.run({"op": "create", "chat_id": "C1"}, deps)["status"] == "error"     # no app


def test_usecase_per_chat_cap(monkeypatch):
    monkeypatch.setenv("ALERT_MAX_SUBS_PER_CHAT", "1")
    deps = _deps_with_subs()
    uc = ManageSubscriptionUseCase()
    assert uc.run({"op": "create", "chat_id": "C1", "app": "a"}, deps)["status"] == "success"
    capped = uc.run({"op": "create", "chat_id": "C1", "app": "b"}, deps)
    assert capped["status"] == "error"


def test_usecase_delete_scoped_to_chat():
    deps = _deps_with_subs()
    uc = ManageSubscriptionUseCase()
    sid = uc.run({"op": "create", "chat_id": "C1", "app": "a"}, deps)["subscription"]["id"]
    assert uc.run({"op": "delete", "chat_id": "C2", "id": sid}, deps)["status"] == "error"  # not owner
    assert uc.run({"op": "delete", "chat_id": "C1", "id": sid}, deps)["status"] == "success"


def test_usecase_test_op_dry_run(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    deps = _deps_with_subs()
    r = ManageSubscriptionUseCase().run({"op": "test", "chat_id": "C1", "app": "zalo"}, deps)
    assert r["status"] == "success" and r["delivery"]["status"] == "dry_run"


# --- per-recipient telegram send --------------------------------------------
def test_telegram_per_call_chat_id_overrides_default():
    calls = []
    n = TelegramNotifier("TOK", "DEFAULT", transport=lambda url, p: calls.append(p))
    n.send("hi", chat_id="OVERRIDE")
    assert calls[0]["chat_id"] == "OVERRIDE"
    n.send("again")  # falls back to instance default
    assert calls[1]["chat_id"] == "DEFAULT"


def test_telegram_no_chat_id_is_error():
    n = TelegramNotifier("TOK", "", transport=lambda url, p: None)
    assert n.send("hi")["status"] == "error"


# --- full subscription cycle -------------------------------------------------
class FakeMeta(AppDataConnector):
    name = "fakemeta"
    stores = {"ios"}

    def capabilities(self):
        return {CAP_METADATA}

    def get_metadata(self, app_id, store="ios", country=None, lang=None):
        return AppMetadata(app_id=app_id, name="FakeApp", store="ios",
                           version="2.0", avg_rating=1.95, rating_count=350000)


def test_background_scheduler_on_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)     # unset → runs
    monkeypatch.setenv("SCHEDULER_INTERVAL_SECONDS", "3600")  # one immediate cycle, then idle
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)   # dry-run, no network
    from scheduler.watch import start_background_scheduler
    t = start_background_scheduler(_deps_with_subs())         # empty store → first cycle is a no-op
    assert t is not None and t.daemon and t.is_alive()


def test_background_scheduler_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ENABLE_SCHEDULER", "0")               # explicit opt-out
    from scheduler.watch import start_background_scheduler
    assert start_background_scheduler(_deps_with_subs()) is None


def test_subscription_cycle_delivers_then_dedups():
    now = datetime(2026, 6, 15, 9, 0, 0)
    snap = SnapshotStore(tempfile.mkdtemp())
    snap.save(Snapshot(captured_at="2026-06-01", app_id="999", store="ios",
                       version="1.0", avg_rating=2.5, rating_count=349000, rank=None))
    subs = _store()
    sub = subs.add(Subscription(chat_id="C-USER", app="999", store="ios",
                                freq="daily", hour=now.hour, lang="vi"))
    deps = Deps(connectors=[FakeMeta()], storage=snap, subscriptions=subs)

    assert len(due_subscriptions(deps, now)) == 1
    notifier = DryRunNotifier()
    report = run_subscription_cycle(deps, notifier, now=now)
    assert report["alerted"] == 1
    assert notifier.sent[0][1] == "C-USER"           # delivered to the sub's own chat
    assert "Rating" in notifier.sent[0][0]
    assert subs.get(sub.id).last_sent == "2026-06-15"  # stamped

    # Same hour again → not due (last_sent guard) → nothing sent.
    report2 = run_subscription_cycle(deps, notifier, now=now)
    assert report2["watched"] == 0 and len(notifier.sent) == 1
