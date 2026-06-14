"""Sheet UC4 — KPI dashboard for PM.

A KPI summary for an app over time from the daily snapshot store — rating, category
rank, ratings volume and version, plus the trend series and first→latest deltas.
Free slice: downloads / revenue / DAU need a paid source (UC3), so this covers the
rating / rank / ratings-volume KPIs measurable for free.

History accrues from snapshots (ephemeral in a container → back with AgentBase
Memory for a durable trend); day-1 shows the current point with the trend filling
in over subsequent runs.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from core.lang import detect_lang, market_for
from usecases.base import UseCase, looks_like_id, snapshot_app


class KpiDashboardUseCase(UseCase):
    name = "uc4_kpi_dashboard"
    description = (
        "KPI dashboard / trend for an app over time — rating, category rank, ratings "
        "volume and version from saved snapshots, with first→latest deltas. Use for "
        "'dashboard', 'KPI', 'tổng hợp chỉ số', 'xu hướng rating/rank theo thời gian'. "
        "Downloads/revenue need a paid source (omitted). NOT a one-off metadata lookup "
        "(uc1_store_metadata), a release verdict (uc6_version_impact), or anomaly alerts "
        "(uc9_trend_alert)."
    )
    input_schema = {
        "app": "app name to search, or a store id",
        "store": "ios | android | both (default both)",
        "country": "two-letter store country (default from language)",
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
                futs = {s: ex.submit(self._one, app_query, s, country, review_lang, lang, deps)
                        for s in ("ios", "android")}
                platforms = {s: f.result() for s, f in futs.items()}
            return {"use_case": self.name, "mode": "cross_platform", "lang": lang,
                    "app_query": app_query, "platforms": platforms}
        return self._one(app_query, store, country, review_lang, lang, deps)

    def _one(self, app_query, store, country, review_lang, lang, deps) -> dict:
        snap = snapshot_app(app_query, store, deps, country, review_lang)
        if snap is None:
            return {"use_case": self.name, "error": f"could not resolve/fetch '{app_query}' on {store}"}
        meta, rank, rank_chart, history = snap["meta"], snap["rank"], snap["rank_chart"], snap["history"]
        vi = lang == "vi"

        # One row per day (last snapshot of each captured_at), chronological.
        by_day: dict[str, dict] = {}
        for s in history:
            by_day[s.captured_at] = {"date": s.captured_at, "rating": s.avg_rating,
                                     "rank": s.rank, "ratings_count": s.rating_count, "version": s.version}
        trend = [by_day[d] for d in sorted(by_day)]

        kpis = {
            "rating": round(meta.avg_rating, 2) if meta.avg_rating is not None else None,
            "rank": rank, "rank_chart": rank_chart,
            "ratings_count": meta.rating_count, "version": meta.version,
            "category": meta.category, "price": meta.price,
        }
        deltas = {"since": None, "rating": None, "rank": None, "ratings_count": None}
        if len(trend) >= 2:
            first, last = trend[0], trend[-1]
            deltas["since"] = first["date"]
            if first["rating"] is not None and last["rating"] is not None:
                deltas["rating"] = round(last["rating"] - first["rating"], 3)
            if first["rank"] and last["rank"]:
                deltas["rank"] = last["rank"] - first["rank"]
            if first["ratings_count"] is not None and last["ratings_count"] is not None:
                deltas["ratings_count"] = last["ratings_count"] - first["ratings_count"]

        notes = ["Downloads/doanh thu/DAU cần nguồn paid (UC3) — chưa có." if vi
                 else "Downloads/revenue/DAU need a paid source (UC3) — omitted."]
        if len(trend) < 2:
            notes.append("Mới có 1 mốc — xu hướng sẽ hiện từ các lần chạy sau." if vi
                         else "Only one data point — the trend fills in over subsequent runs.")

        if vi:
            summary = (f"KPI {meta.name}: rating {kpis['rating']}, rank {rank_chart} #{rank if rank else 'n/a'}, "
                       f"{kpis['ratings_count']} lượt rating. {len(trend)} mốc dữ liệu.")
        else:
            summary = (f"KPIs for {meta.name}: rating {kpis['rating']}, rank {rank_chart} #{rank if rank else 'n/a'}, "
                       f"{kpis['ratings_count']} ratings. {len(trend)} data point(s).")
        return {"use_case": self.name, "lang": lang,
                "app": {"app_id": meta.app_id, "name": meta.name, "store": store},
                "kpis": kpis, "deltas": deltas, "trend": trend[-14:], "notes": notes, "summary": summary}
