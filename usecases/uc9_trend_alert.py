"""Sheet UC9 — Trend detection & anomaly alert.

Flags anomalies in an app's own time series from the daily snapshot store — rating
drops, category-rank slides, and version changes — with severity. The free slice
covers the single-app metric trend (rating / rank / version); the cross-competitor
"rising feature" detection needs the UC5 feature timeline (not free), and a deeper
negative-review spike needs a stored sentiment series.

Snapshots are append-only and ephemeral in a container, so day-1 only seeds a
baseline; alerts appear once ≥2 snapshots exist (back with AgentBase Memory for
durability across redeploys).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from core.lang import detect_lang, market_for
from usecases.base import UseCase, looks_like_id, snapshot_app

_RATING_DROP = -0.1   # default alert threshold (rating points)
_RANK_SLIDE = 3       # positions worse before alerting


class TrendAlertUseCase(UseCase):
    name = "uc9_trend_alert"
    description = (
        "Anomaly ALERTS for an app from its snapshot history — flags rating drops, "
        "category-rank slides and version changes, with severity. Use for 'cảnh báo', "
        "'có bất thường không', 'rating/rank có tụt không', 'theo dõi biến động', "
        "'alert / anomaly / trend'. NOT a full KPI dashboard (uc4_kpi_dashboard), a "
        "release-health verdict (uc6_version_impact), or a causal hypothesis."
    )
    input_schema = {
        "app": "app name to search, or a store id",
        "store": "ios | android | both (default both)",
        "country": "two-letter store country (default from language)",
        "rating_drop": "rating-drop alert threshold (default -0.1)",
    }

    def run(self, params: dict, deps, context=None) -> dict:
        store = (params.get("store") or "both").lower()
        app_query = (params.get("app") or "").strip()
        if not app_query:
            return {"use_case": self.name, "error": "missing 'app' parameter"}
        lang = (params.get("lang") or detect_lang(app_query)).lower()
        market_country, review_lang = market_for(lang)
        country = params.get("country") or market_country

        if store in ("both", "all", "cross", "cross_platform"):
            if app_query.isdigit():
                store = "ios"
            elif looks_like_id(app_query, "android"):
                store = "android"
        if store in ("both", "all", "cross", "cross_platform"):
            with ThreadPoolExecutor(max_workers=2) as ex:
                futs = {s: ex.submit(self._one, app_query, s, country, review_lang, lang, deps, params)
                        for s in ("ios", "android")}
                platforms = {s: f.result() for s, f in futs.items()}
            return {"use_case": self.name, "mode": "cross_platform", "lang": lang,
                    "app_query": app_query, "platforms": platforms}
        return self._one(app_query, store, country, review_lang, lang, deps, params)

    def _one(self, app_query, store, country, review_lang, lang, deps, params) -> dict:
        snap = snapshot_app(app_query, store, deps, country, review_lang)
        if snap is None:
            return {"use_case": self.name, "error": f"could not resolve/fetch '{app_query}' on {store}"}
        meta, rank, rank_chart, history = snap["meta"], snap["rank"], snap["rank_chart"], snap["history"]
        vi = lang == "vi"
        current = {"rating": round(meta.avg_rating, 2) if meta.avg_rating is not None else None,
                   "rank": rank, "rank_chart": rank_chart, "version": meta.version}
        app = {"app_id": meta.app_id, "name": meta.name, "store": store}

        prior = history[-2] if len(history) >= 2 else None
        if prior is None:
            return {
                "use_case": self.name, "lang": lang, "app": app, "current": current,
                "baseline_date": None, "alerts": [], "status": "baseline_seeded",
                "summary": (f"{meta.name}: đã lưu mốc đầu — cảnh báo sẽ có từ lần chạy sau."
                            if vi else f"{meta.name}: baseline seeded — alerts from the next run."),
            }

        th = float(params.get("rating_drop", _RATING_DROP) or _RATING_DROP)
        alerts: list[dict] = []
        if prior.avg_rating is not None and meta.avg_rating is not None:
            d = round(meta.avg_rating - prior.avg_rating, 3)
            if d <= th:
                sev = "high" if d <= -0.3 else "medium"
                alerts.append({"type": "rating_drop", "severity": sev,
                               "message": (f"Rating giảm {d:+.2f} ({round(prior.avg_rating,2)}→{round(meta.avg_rating,2)})"
                                           if vi else f"Rating dropped {d:+.2f} ({round(prior.avg_rating,2)}→{round(meta.avg_rating,2)})")})
        if prior.rank and rank:
            rd = rank - prior.rank  # positive = slid down the chart
            if rd >= _RANK_SLIDE:
                alerts.append({"type": "rank_slide", "severity": "high" if rd >= 10 else "medium",
                               "message": (f"Rank {rank_chart} tụt {rd} bậc (#{prior.rank}→#{rank})"
                                           if vi else f"{rank_chart} rank slid {rd} (#{prior.rank}→#{rank})")})
            elif rd <= -_RANK_SLIDE:
                alerts.append({"type": "rank_gain", "severity": "info",
                               "message": (f"Rank {rank_chart} tăng {-rd} bậc (#{prior.rank}→#{rank})"
                                           if vi else f"{rank_chart} rank up {-rd} (#{prior.rank}→#{rank})")})
        if meta.version and prior.version and meta.version != prior.version:
            alerts.append({"type": "version_change", "severity": "info",
                           "message": (f"Có bản cập nhật mới: {prior.version} → {meta.version}"
                                       if vi else f"New version: {prior.version} → {meta.version}")})

        if vi:
            summary = (f"{meta.name}: {len(alerts)} cảnh báo so với {prior.captured_at}."
                       if alerts else f"{meta.name}: không có bất thường so với {prior.captured_at}.")
        else:
            summary = (f"{meta.name}: {len(alerts)} alert(s) since {prior.captured_at}."
                       if alerts else f"{meta.name}: no anomalies since {prior.captured_at}.")
        return {"use_case": self.name, "lang": lang, "app": app, "current": current,
                "baseline_date": prior.captured_at, "alerts": alerts,
                "status": "alert" if alerts else "ok", "summary": summary}
