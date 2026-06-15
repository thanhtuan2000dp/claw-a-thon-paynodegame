"""Manage UC9 alert subscriptions (self-serve, per Telegram chat).

A subscription is "send anomaly alerts for app X to my Telegram chat on schedule
S". Users supply only a ``chat_id`` (a destination, not a secret) — the bot token
stays server-side. Reached from the chat UI's Alerts panel as
``{action:"manage_subscription", params:{op:..., chat_id:...}}``.

Ops: ``create`` | ``list`` | ``delete`` | ``test``. All require ``chat_id``;
``test`` does a live delivery so the user can confirm their chat works.
"""

from __future__ import annotations

import os

from core.alerts import make_notifier
from storage.subscriptions import Subscription
from usecases.base import UseCase

_FREQS = ("daily", "weekly")
_STORES = ("ios", "android", "both")
_DEFAULT_MAX = 200
_DEFAULT_MAX_PER_CHAT = 20


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _vi(params: dict) -> bool:
    return (params.get("lang") or "vi").lower() != "en"


class ManageSubscriptionUseCase(UseCase):
    name = "manage_subscription"
    description = (
        "Manage a user's anomaly-alert subscriptions: register/list/delete which app's "
        "UC9 alerts go to which Telegram chat on what schedule, and send a test alert. "
        "Driven by the chat UI Alerts panel, not by free-text routing."
    )
    input_schema = {
        "op": "create | list | delete | test",
        "chat_id": "Telegram chat id to deliver to (the user's identity)",
        "app": "app name or store id to watch (create/test)",
        "store": "ios | android | both (default ios)",
        "freq": "daily | weekly (default daily)",
        "hour": "local hour 0-23 in ALERT_TZ (default 9)",
        "weekday": "0=Mon..6=Sun (required when freq=weekly)",
        "lang": "vi | en — alert + UI language",
        "id": "subscription id (delete)",
    }

    def run(self, params: dict, deps, context=None) -> dict:
        op = (params.get("op") or "").strip().lower()
        chat_id = str(params.get("chat_id") or "").strip()
        vi = _vi(params)
        if not chat_id:
            return self._err(self.name, "thiếu chat_id" if vi else "missing chat_id")
        if op == "create":
            return self._create(params, deps, chat_id, vi)
        if op == "list":
            return self._list(deps, chat_id, vi)
        if op == "delete":
            return self._delete(params, deps, chat_id, vi)
        if op == "test":
            return self._test(params, chat_id, vi)
        return self._err(self.name, f"op không hợp lệ: '{op}'" if vi else f"invalid op: '{op}'")

    # ------------------------------------------------------------------
    def _create(self, params, deps, chat_id, vi) -> dict:
        app = (params.get("app") or "").strip()
        if not app:
            return self._err(self.name, "thiếu 'app'" if vi else "missing 'app'")
        store = (params.get("store") or "ios").lower()
        if store not in _STORES:
            store = "ios"
        freq = (params.get("freq") or "daily").lower()
        if freq not in _FREQS:
            freq = "daily"
        hour = max(0, min(23, _as_int(params.get("hour"), 9)))
        weekday = None
        if freq == "weekly":
            weekday = _as_int(params.get("weekday"), 0)
            if not 0 <= weekday <= 6:
                return self._err(self.name, "weekday phải 0-6 (T2-CN)" if vi else "weekday must be 0-6 (Mon-Sun)")

        max_total = _as_int(os.environ.get("ALERT_MAX_SUBS"), _DEFAULT_MAX)
        max_chat = _as_int(os.environ.get("ALERT_MAX_SUBS_PER_CHAT"), _DEFAULT_MAX_PER_CHAT)
        if deps.subscriptions.count() >= max_total:
            return self._err(self.name, "đã đạt giới hạn đăng ký của hệ thống" if vi
                             else "system subscription limit reached")
        if deps.subscriptions.count(chat_id) >= max_chat:
            return self._err(self.name, f"mỗi chat tối đa {max_chat} đăng ký" if vi
                             else f"max {max_chat} subscriptions per chat")

        sub = Subscription(
            chat_id=chat_id, app=app, store=store,
            lang=(params.get("lang") or None), country=(params.get("country") or None),
            freq=freq, hour=hour, weekday=weekday, label=(params.get("label") or None),
            created_at=_now_iso(),
        )
        deps.subscriptions.add(sub)
        when = self._when_text(sub, vi)
        msg = (f"Đã đăng ký cảnh báo '{app}' ({store}), {when}." if vi
               else f"Subscribed to '{app}' ({store}) alerts, {when}.")
        return {"use_case": self.name, "op": "create", "status": "success",
                "subscription": _public(sub), "message": msg}

    def _list(self, deps, chat_id, vi) -> dict:
        subs = [_public(s) for s in deps.subscriptions.list(chat_id)]
        msg = (f"Bạn có {len(subs)} đăng ký." if vi else f"You have {len(subs)} subscription(s).")
        return {"use_case": self.name, "op": "list", "status": "success",
                "subscriptions": subs, "message": msg}

    def _delete(self, params, deps, chat_id, vi) -> dict:
        sub_id = str(params.get("id") or "").strip()
        if not sub_id:
            return self._err(self.name, "thiếu 'id'" if vi else "missing 'id'")
        ok = deps.subscriptions.delete(sub_id, chat_id)
        if not ok:
            return self._err(self.name, "không tìm thấy đăng ký" if vi else "subscription not found")
        return {"use_case": self.name, "op": "delete", "status": "success",
                "message": "Đã xoá đăng ký." if vi else "Subscription deleted."}

    def _test(self, params, chat_id, vi) -> dict:
        app = (params.get("app") or "").strip()
        text = (f"🔔 Cảnh báo thử nghiệm{(' cho ' + app) if app else ''} — kênh Telegram của bạn hoạt động."
                if vi else
                f"🔔 Test alert{(' for ' + app) if app else ''} — your Telegram channel works.")
        delivery = make_notifier().send(text, chat_id=chat_id)
        ok = delivery.get("status") in ("sent", "dry_run")
        if delivery.get("status") == "dry_run":
            note = ("Server chưa cấu hình TELEGRAM_BOT_TOKEN — mới ở chế độ thử (chưa gửi thật)." if vi
                    else "Server has no TELEGRAM_BOT_TOKEN yet — dry-run only (nothing sent).")
        elif ok:
            note = "Đã gửi — kiểm tra Telegram." if vi else "Sent — check Telegram."
        else:
            note = (f"Gửi thất bại: {delivery.get('error')}" if vi
                    else f"Send failed: {delivery.get('error')}")
        return {"use_case": self.name, "op": "test",
                "status": "success" if ok else "error", "delivery": delivery, "message": note}

    # ------------------------------------------------------------------
    def _when_text(self, sub: Subscription, vi: bool) -> str:
        if sub.freq == "weekly":
            days_vi = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"]
            days_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            d = (days_vi if vi else days_en)[sub.weekday or 0]
            return (f"hằng tuần {d} lúc {sub.hour:02d}:00" if vi else f"weekly on {d} at {sub.hour:02d}:00")
        return (f"hằng ngày lúc {sub.hour:02d}:00" if vi else f"daily at {sub.hour:02d}:00")

    @staticmethod
    def _err(use_case: str, message: str) -> dict:
        return {"use_case": use_case, "status": "error", "error": message, "message": message}


def _public(sub: Subscription) -> dict:
    """A subscription as returned to the UI — same fields (chat_id is the user's own)."""
    return {"id": sub.id, "app": sub.app, "store": sub.store, "chat_id": sub.chat_id,
            "freq": sub.freq, "hour": sub.hour, "weekday": sub.weekday,
            "lang": sub.lang, "label": sub.label, "active": sub.active,
            "last_sent": sub.last_sent}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
