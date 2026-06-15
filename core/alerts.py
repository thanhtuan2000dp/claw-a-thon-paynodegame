"""Alert delivery for the UC9 anomaly watch.

A channel-agnostic ``Notifier`` with a Telegram backend and a dry-run fallback.
When ``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_CHAT_ID`` are set, alerts POST to
Telegram's ``sendMessage``; otherwise the notifier runs in **dry-run** mode (logs
the payload, sends nothing) so the watch is safe to run with no credentials.

Stdlib-only (``urllib``) — no new dependency, and unit-testable by injecting a
notifier or stubbing the HTTP transport. ``send`` never raises: a delivery
failure degrades to an ``error`` status so one bad alert can't sink the cycle.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from abc import ABC, abstractmethod
from typing import Callable, Optional

logger = logging.getLogger("alerts")

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = float(os.environ.get("ALERT_HTTP_TIMEOUT", "10") or 10)

# Severity → marker, most severe first (drives the message header icon).
_SEV_ICON = {"high": "🔴", "medium": "🟠", "info": "🔵"}
_SEV_ORDER = ["high", "medium", "info"]


class Notifier(ABC):
    @abstractmethod
    def send(self, text: str, chat_id: Optional[str] = None) -> dict:
        """Deliver one alert message to ``chat_id`` (or the configured default).
        Returns a status dict; never raises."""


class DryRunNotifier(Notifier):
    """Logs the message and reports ``dry_run`` — used when no channel is configured."""

    channel = "dry_run"

    def __init__(self, reason: str = ""):
        self.reason = reason
        self.sent: list[tuple[str, Optional[str]]] = []  # (text, chat_id) for tests

    def send(self, text: str, chat_id: Optional[str] = None) -> dict:
        self.sent.append((text, chat_id))
        logger.info("[alert dry-run → %s] %s", chat_id or "-", text.replace("\n", " | "))
        return {"channel": self.channel, "status": "dry_run", "reason": self.reason}


class TelegramNotifier(Notifier):
    """Sends via Telegram Bot ``sendMessage``. The bot ``token`` is the shared
    server secret; ``chat_id`` is the per-recipient destination — passed per
    ``send`` (subscriptions) or falling back to the instance default (global
    watchlist). ``transport`` is injectable for tests."""

    channel = "telegram"

    def __init__(self, token: str, chat_id: str = "", parse_mode: str = "",
                 transport: Optional[Callable[[str, dict], None]] = None):
        self.token = token
        self.chat_id = chat_id          # default destination (global watchlist)
        self.parse_mode = parse_mode    # "" = plain text (no escaping pitfalls)
        self._transport = transport or _http_post_json

    def send(self, text: str, chat_id: Optional[str] = None) -> dict:
        dest = (chat_id or self.chat_id or "").strip()
        if not dest:
            return {"channel": self.channel, "status": "error", "error": "no chat_id"}
        payload = {"chat_id": dest, "text": text, "disable_web_page_preview": True}
        if self.parse_mode:
            payload["parse_mode"] = self.parse_mode
        try:
            self._transport(_TELEGRAM_API.format(token=self.token), payload)
            return {"channel": self.channel, "status": "sent"}
        except Exception as exc:  # noqa: BLE001 - delivery must not crash the watch
            logger.warning("telegram send failed: %s", exc)
            return {"channel": self.channel, "status": "error", "error": str(exc)}


def _http_post_json(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 - fixed https host
        status = getattr(resp, "status", 200)
        if status >= 300:
            raise RuntimeError(f"HTTP {status}")


def make_notifier(env: Optional[dict] = None) -> Notifier:
    """Telegram when the bot token is present, else a dry-run notifier.

    The token is all that's required: per-subscription delivery supplies its own
    ``chat_id`` at ``send`` time. ``TELEGRAM_CHAT_ID`` only sets the default
    destination for the global env watchlist."""
    env = env if env is not None else os.environ
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    if token:
        return TelegramNotifier(token, chat_id, parse_mode=(env.get("ALERT_PARSE_MODE") or "").strip())
    return DryRunNotifier(reason="not set: TELEGRAM_BOT_TOKEN")


# --------------------------------------------------------------------------
# Formatting a UC9 result into an alert message (None when there's nothing to send).

def _top_severity(alerts: list[dict]) -> str:
    sevs = {a.get("severity") for a in alerts}
    for s in _SEV_ORDER:
        if s in sevs:
            return s
    return "info"


def _one_block(res: dict) -> Optional[str]:
    alerts = res.get("alerts") or []
    if res.get("status") != "alert" or not alerts:
        return None
    vi = res.get("lang") == "vi"
    app = res.get("app") or {}
    name, store = app.get("name") or "?", app.get("store") or "?"
    word = "cảnh báo" if vi else ("alert" if len(alerts) == 1 else "alerts")
    head = f"{_SEV_ICON.get(_top_severity(alerts), '🔔')} {name} ({store}) — {len(alerts)} {word}"
    base = res.get("baseline_date")
    if base:
        head += f"  [{'so với' if vi else 'vs'} {base}]"
    lines = [head] + [f"• [{(a.get('severity') or '?').upper()}] {a.get('message', '')}" for a in alerts]
    return "\n".join(lines)


def format_uc9_alert(res: dict) -> Optional[str]:
    """Build the alert message for a UC9 result (single-store or cross_platform).
    Returns None when the result carries no anomalies."""
    if res.get("mode") == "cross_platform":
        blocks = [b for b in (_one_block(p) for p in (res.get("platforms") or {}).values()) if b]
        if not blocks:
            return None
        vi = res.get("lang") == "vi"
        header = (f"⚠️ {res.get('app_query', 'app')} — phát hiện bất thường" if vi
                  else f"⚠️ {res.get('app_query', 'app')} — anomalies detected")
        return "\n\n".join([header, *blocks])
    return _one_block(res)
