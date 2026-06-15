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
from typing import Optional

from core.alerts import Notifier, format_uc9_alert, make_notifier
from usecases.uc9_trend_alert import TrendAlertUseCase

logger = logging.getLogger("scheduler.watch")


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
            results.append({"app": entry["app"], "store": entry.get("store"),
                            "uc_status": "error", "delivery": {"status": "error", "error": str(exc)}})
            continue
        msg = format_uc9_alert(res)
        delivery = notifier.send(msg) if msg else {"status": "no_alert"}
        results.append({"app": entry["app"], "store": entry.get("store"),
                        "uc_status": _uc_status(res), "delivery": delivery})

    alerted = sum(1 for r in results if r["delivery"].get("status") in ("sent", "dry_run"))
    return {"watched": len(watchlist), "alerted": alerted, "results": results}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from core.deps import build_deps  # local import: keeps the module import-light for tests

    watchlist = load_watchlist()
    notifier = make_notifier()
    if not watchlist:
        logger.warning("watchlist is empty — set WATCHLIST_FILE or ALERT_WATCHLIST")
    report = run_watch_cycle(build_deps(), notifier, watchlist)
    logger.info("watch cycle: %d watched, %d alerted via %s",
                report["watched"], report["alerted"], getattr(notifier, "channel", "?"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # python -m scheduler.watch
    raise SystemExit(main())
