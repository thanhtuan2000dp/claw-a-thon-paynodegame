"""UC9 anomaly watch — runs the trend-alert use case over a watchlist and
delivers any anomalies through a ``Notifier`` (Telegram, or dry-run when
unconfigured).

Designed to be driven by an **external** scheduler — platform cron / k8s CronJob
/ unix cron — one process per cycle, so it never competes with the request-
serving event loop and needs no in-process timer:

    python -m scheduler                 # run one watch cycle, print a JSON report

What to watch (first source that resolves):
  - ``WATCHLIST_FILE``  → path to a JSON list of objects
        [{"app": "Zalo", "store": "both", "lang": "vi"}, {"app": "284882215"}]
  - ``ALERT_WATCHLIST`` → shorthand "app|store|lang" entries, comma-separated
        "Zalo|both|vi, com.spotify.music|android|en"

The cycle is pure given (deps, notifier, watchlist) — inject fakes to test it
offline; ``main()`` wires the real deps + notifier from the environment.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from core.alerts import Notifier, format_uc9_alert, make_notifier
from storage.subscriptions import Subscription
from usecases.uc9_trend_alert import TrendAlertUseCase

logger = logging.getLogger("scheduler.watch")


def _now() -> datetime:
    """Current time in the configured alert timezone (``ALERT_TZ``)."""
    tz = os.environ.get("ALERT_TZ", "Asia/Ho_Chi_Minh")
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz))
    except Exception:  # noqa: BLE001 - missing tzdata → fall back to local time
        return datetime.now()


def _is_due(sub: Subscription, now: datetime) -> bool:
    """A subscription is due when it's active, the hour (and weekday, if weekly)
    match ``now``, and it hasn't already been delivered today (idempotency guard
    that holds even if cron fires more than once an hour)."""
    if not sub.active or now.hour != int(sub.hour):
        return False
    if sub.freq == "weekly" and sub.weekday is not None and now.weekday() != int(sub.weekday):
        return False
    return (sub.last_sent or "")[:10] != now.date().isoformat()


def due_subscriptions(deps, now: Optional[datetime] = None) -> list[dict]:
    """Active subscriptions due at ``now`` → watch entries carrying chat_id + _sub_id."""
    now = now or _now()
    out: list[dict] = []
    for sub in deps.subscriptions.all_active():
        if _is_due(sub, now):
            entry = {"app": sub.app, "store": sub.store, "chat_id": sub.chat_id, "_sub_id": sub.id}
            if sub.lang:
                entry["lang"] = sub.lang
            if sub.country:
                entry["country"] = sub.country
            out.append(entry)
    return out


def load_watchlist(env: Optional[dict] = None) -> list[dict]:
    """Resolve the watchlist from the environment. Returns normalised entries
    ``{"app", "store", "lang"?, "country"?}`` (empty list if nothing configured)."""
    env = env if env is not None else os.environ
    path = (env.get("WATCHLIST_FILE") or "").strip()
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return [_normalise(e) for e in raw if _normalise(e)]
    shorthand = (env.get("ALERT_WATCHLIST") or "").strip()
    if shorthand:
        out = []
        for chunk in shorthand.split(","):
            parts = [p.strip() for p in chunk.split("|")]
            if not parts or not parts[0]:
                continue
            entry = {"app": parts[0]}
            if len(parts) > 1 and parts[1]:
                entry["store"] = parts[1]
            if len(parts) > 2 and parts[2]:
                entry["lang"] = parts[2]
            out.append(_normalise(entry))
        return [e for e in out if e]
    return []


def _normalise(entry) -> Optional[dict]:
    if isinstance(entry, str):
        entry = {"app": entry}
    if not isinstance(entry, dict) or not (entry.get("app") or "").strip():
        return None
    out = {"app": entry["app"].strip(), "store": (entry.get("store") or "both").strip()}
    for k in ("lang", "country"):
        if entry.get(k):
            out[k] = str(entry[k]).strip()
    return out


def _uc_status(res: dict) -> str:
    if res.get("mode") == "cross_platform":
        plats = (res.get("platforms") or {}).values()
        return "alert" if any(p.get("status") == "alert" for p in plats) else "ok"
    return res.get("status", "unknown")


def run_watch_cycle(deps, notifier: Notifier, watchlist: list[dict],
                    use_case: Optional[TrendAlertUseCase] = None) -> dict:
    """Run UC9 for each watched app and deliver anomalies. Returns a report:
    ``{"watched", "alerted", "results": [{app, store, uc_status, delivery}]}``."""
    uc = use_case or TrendAlertUseCase()
    results: list[dict] = []
    for entry in watchlist:
        params = {"app": entry["app"], "store": entry.get("store", "both")}
        for k in ("lang", "country"):
            if entry.get(k):
                params[k] = entry[k]
        try:
            res = uc.run(params, deps)
        except Exception as exc:  # noqa: BLE001 - one bad app must not sink the cycle
            logger.warning("watch failed for %s: %s", entry["app"], exc)
            results.append({"app": entry["app"], "store": entry.get("store"), "sub_id": entry.get("_sub_id"),
                            "uc_status": "error", "delivery": {"status": "error", "error": str(exc)}})
            continue
        msg = format_uc9_alert(res)
        delivery = notifier.send(msg, chat_id=entry.get("chat_id")) if msg else {"status": "no_alert"}
        results.append({"app": entry["app"], "store": entry.get("store"), "sub_id": entry.get("_sub_id"),
                        "uc_status": _uc_status(res), "delivery": delivery})

    alerted = sum(1 for r in results if r["delivery"].get("status") in ("sent", "dry_run"))
    return {"watched": len(watchlist), "alerted": alerted, "results": results}


def run_subscription_cycle(deps, notifier: Notifier, now: Optional[datetime] = None) -> dict:
    """Deliver to every user subscription due at ``now``, then stamp ``last_sent``
    so the same period won't fire twice (idempotent across cron frequency)."""
    now = now or _now()
    entries = due_subscriptions(deps, now)
    report = run_watch_cycle(deps, notifier, entries)
    today = now.date().isoformat()
    for r in report["results"]:
        if r.get("sub_id") and r["delivery"].get("status") in ("sent", "dry_run"):
            deps.subscriptions.mark_sent(r["sub_id"], today)
    return report


def start_background_scheduler(deps, notifier: Optional[Notifier] = None):
    """In-process scheduler — **on by default**. Spawns a daemon thread that runs
    the env watchlist + user-subscription cycles every ``SCHEDULER_INTERVAL_SECONDS``
    (default 300), so alerts are delivered at their scheduled hour without an
    external cron. Set ``ENABLE_SCHEDULER=0`` (or false/no/off) to disable it (e.g.
    when running multiple replicas and driving the watch from a single cron instead).
    Returns the thread, or None when disabled. The ``last_sent`` guard keeps frequent
    polling idempotent."""
    if (os.environ.get("ENABLE_SCHEDULER") or "").strip().lower() in ("0", "false", "no", "off"):
        return None
    import threading
    import time

    interval = max(60, int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "300") or 300))
    notifier = notifier or make_notifier()

    def _loop():
        logger.info("in-process scheduler on: every %ds via %s",
                    interval, getattr(notifier, "channel", "?"))
        while True:
            try:
                wl = load_watchlist()
                if wl:
                    run_watch_cycle(deps, notifier, wl)
                rep = run_subscription_cycle(deps, notifier)
                if rep.get("alerted"):
                    logger.info("scheduler delivered %d subscription alert(s)", rep["alerted"])
            except Exception as exc:  # noqa: BLE001 - keep the loop alive across failures
                logger.warning("scheduler cycle error: %s", exc)
            time.sleep(interval)

    t = threading.Thread(target=_loop, name="veridex-scheduler", daemon=True)
    t.start()
    return t


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        from dotenv import load_dotenv  # match the server: let cron read .env too
        load_dotenv()
    except Exception:  # noqa: BLE001 - dotenv optional; ambient env still works
        pass
    from core.deps import build_deps  # local import: keeps the module import-light for tests

    deps = build_deps()
    notifier = make_notifier()

    # 1) Global env watchlist (operator-configured, back-compat).
    watchlist = load_watchlist()
    env_report = run_watch_cycle(deps, notifier, watchlist) if watchlist else {"watched": 0, "alerted": 0, "results": []}
    # 2) Per-user subscriptions due this hour.
    sub_report = run_subscription_cycle(deps, notifier)

    report = {"env_watchlist": env_report, "subscriptions": sub_report,
              "alerted": env_report["alerted"] + sub_report["alerted"]}
    logger.info("watch cycle: env %d/%d, subs %d/%d, %d alerted via %s",
                env_report["alerted"], env_report["watched"],
                sub_report["alerted"], sub_report["watched"],
                report["alerted"], getattr(notifier, "channel", "?"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # python -m scheduler.watch
    raise SystemExit(main())
