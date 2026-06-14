"""Sheet UC1 — Crawl metadata & store data.

For any app: resolve it, pull normalised store-listing metadata (title, category,
price, icon, screenshots, description, current version + release date, overall
rating), record the current top-chart rank (iOS only — free), snapshot it for the
day, and report what changed since the last snapshot (rating / version / rank).

Reuses the connectors, snapshot store, and resolve helper; no greennode-agentbase
import, so it is unit-testable against live iTunes / Google Play.

Limits (no free source): Android ranking and full version history are
unavailable — version history accrues from daily snapshots over time.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from connectors.base import CAP_METADATA, CAP_RANKING, ConnectorError
from core.lang import detect_lang, market_for
from storage.snapshots import Snapshot
from usecases.base import UseCase, looks_like_id, resolve_app


def _names_match(a: str, b: str) -> bool:
    """Loose match on the first alphanumeric token (catches store name variants
    while flagging genuinely different apps)."""
    def first_tok(s: str) -> str:
        toks = re.findall(r"[a-z0-9]+", s.lower())
        return toks[0] if toks else ""

    return bool(first_tok(a)) and first_tok(a) == first_tok(b)


class StoreMetadataUseCase(UseCase):
    name = "uc1_store_metadata"
    description = (
        "Current store listing + chart rank for an app — category, price, version, icon, "
        "screenshots, overall rating — plus what changed since the last snapshot. Answers "
        "'app info / rank / price / category'. Static listing facts; NOT reviews, sentiment, "
        "or causal analysis."
    )
    input_schema = {
        "app": "app name to search, or a store id (iOS trackId / Android package)",
        "store": "ios | android | both (default both)",
        "country": "two-letter store country (default from language)",
    }

    def run(self, params: dict, deps, context=None) -> dict:
        store = (params.get("store") or "both").lower()
        app_query = (params.get("app") or "").strip()
        if not app_query:
            return {"use_case": self.name, "error": "missing 'app' parameter"}

        lang = (params.get("lang") or detect_lang(app_query)).lower()
        market_country, _ = market_for(lang)
        country = params.get("country") or market_country

        # A store-specific id only resolves on its own store → narrow a "both" request.
        if store in ("both", "all", "cross", "cross_platform"):
            if app_query.isdigit():
                store = "ios"
            elif looks_like_id(app_query, "android"):
                store = "android"

        if store in ("both", "all", "cross", "cross_platform"):
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=2) as ex:
                futures = {
                    s: ex.submit(self._analyze_one, app_query, s, country, lang, deps)
                    for s in ("ios", "android")
                }
                platforms = {s: f.result() for s, f in futures.items()}
            result = {
                "use_case": self.name,
                "mode": "cross_platform",
                "lang": lang,
                "app_query": app_query,
                "platforms": platforms,
            }
            names = {s: (p.get("metadata", {}).get("name") or "")
                     for s, p in platforms.items() if not p.get("error")}
            ios_n, and_n = names.get("ios", ""), names.get("android", "")
            if ios_n and and_n and not _names_match(ios_n, and_n):
                result["warning"] = (
                    f"⚠️ iOS resolve '{ios_n}', Android resolve '{and_n}' — có thể là 2 app khác nhau."
                    if lang == "vi" else
                    f"⚠️ iOS resolved '{ios_n}', Android '{and_n}' — likely different apps."
                )
            return result
        return self._analyze_one(app_query, store, country, lang, deps)

    def _analyze_one(self, app_query: str, store: str, country: str, lang: str, deps) -> dict:
        notes: list[str] = []

        app_ref = resolve_app(app_query, store, deps, country, lang)
        if app_ref is None or not app_ref.app_id:
            return {"use_case": self.name, "error": f"could not resolve app '{app_query}' on {store}"}

        meta_conn = deps.connector_for(CAP_METADATA, store)
        if meta_conn is None:
            return {"use_case": self.name, "error": f"no metadata source for {store}"}
        try:
            meta = meta_conn.get_metadata(app_ref.app_id, store, country=country, lang=lang)
        except ConnectorError as exc:
            return {"use_case": self.name, "error": f"metadata fetch failed: {exc}"}

        # Ranking — iOS only via the free top-charts feed; Android has no free source.
        rank: Optional[int] = None
        rank_chart: Optional[str] = None
        rank_conn = deps.connector_for(CAP_RANKING, store)
        if rank_conn is not None:
            try:
                rp = rank_conn.get_ranking(meta.app_id, store, "top-free", datetime.utcnow())
                rank, rank_chart = rp.rank, rp.category
            except ConnectorError as exc:
                notes.append(f"Ranking unavailable ({exc}).")
        elif store == "android":
            notes.append("Android chart rank has no free source — omitted."
                         if lang == "en" else
                         "Rank Android không có nguồn free — bỏ qua.")

        release_dt = meta.current_version_release_date

        # Snapshot the day's state, then read history to compute deltas.
        deps.storage.save(
            Snapshot(
                captured_at=datetime.utcnow().date().isoformat(),
                app_id=meta.app_id,
                store=store,
                version=meta.version,
                avg_rating=meta.avg_rating,
                rating_count=meta.rating_count,
                current_version_release_date=release_dt.isoformat() if release_dt else None,
                rank=rank,
            )
        )
        history = deps.storage.history(meta.app_id, store)
        prior = history[-2] if len(history) >= 2 else None
        history_block = {
            "baseline_date": prior.captured_at if prior else None,
            "rating_delta": None,
            "rank_delta": None,
            "version_changed": None,
        }
        if prior:
            if prior.avg_rating is not None and meta.avg_rating is not None:
                history_block["rating_delta"] = round(meta.avg_rating - prior.avg_rating, 3)
            if prior.rank is not None and rank is not None:
                history_block["rank_delta"] = rank - prior.rank  # +ve = dropped down the chart
            history_block["version_changed"] = (meta.version != prior.version)

        metadata = {
            "app_id": meta.app_id,
            "name": meta.name,
            "store": store,
            "publisher": meta.publisher,
            "category": meta.category,
            "price": meta.price,
            "version": meta.version,
            "release_date": release_dt.date().isoformat() if release_dt else None,
            "first_release_date": meta.first_release_date.date().isoformat() if meta.first_release_date else None,
            "avg_rating": meta.avg_rating,
            "rating_count": meta.rating_count,
            "icon_url": meta.icon_url,
            "screenshot_count": len(meta.screenshot_urls or []),
            "screenshot_urls": (meta.screenshot_urls or [])[:5],
            "description": (meta.description or "")[:600] or None,
            "release_notes": (meta.release_notes or "")[:400] or None,
        }
        ranking = {"chart": rank_chart, "rank": rank, "country": country}

        # Persist the normalised row for downstream use cases (dashboard, comparison).
        try:
            deps.storage.save_table(
                "metadata", meta.app_id, store, [{**metadata, "ranking": ranking}],
                captured_at=datetime.utcnow().date().isoformat(),
            )
        except OSError as exc:  # persistence is best-effort; never fail the report
            notes.append(f"Could not persist metadata table ({exc}).")

        summary = self._summarise(metadata, ranking, history_block, lang)
        return {
            "use_case": self.name,
            "lang": lang,
            "app": {"app_id": meta.app_id, "name": meta.name, "store": store},
            "metadata": metadata,
            "ranking": ranking,
            "history": history_block,
            "notes": notes,
            "summary": summary,
        }

    def _summarise(self, metadata: dict, ranking: dict, history: dict, lang: str) -> str:
        name, ver = metadata["name"], metadata["version"] or "?"
        rate = metadata["avg_rating"]
        rank = ranking.get("rank")
        rd = history.get("rating_delta")
        if lang == "vi":
            parts = [f"{name} (v{ver}, {metadata.get('category') or 'n/a'}, {metadata.get('price') or 'n/a'}): "
                     f"rating tổng {rate if rate is not None else 'n/a'}."]
            parts.append(f"Rank {ranking.get('chart')}: #{rank}." if rank else "Ngoài top chart (hoặc không có rank).")
            if rd is not None:
                parts.append(f"Rating đổi {rd:+.3f} từ {history.get('baseline_date')}.")
            if history.get("version_changed"):
                parts.append("Đã lên version mới so với snapshot trước.")
        else:
            parts = [f"{name} (v{ver}, {metadata.get('category') or 'n/a'}, {metadata.get('price') or 'n/a'}): "
                     f"overall rating {rate if rate is not None else 'n/a'}."]
            parts.append(f"Rank {ranking.get('chart')}: #{rank}." if rank else "Outside the top chart (or no rank).")
            if rd is not None:
                parts.append(f"Rating moved {rd:+.3f} since {history.get('baseline_date')}.")
            if history.get("version_changed"):
                parts.append("New version since last snapshot.")
        return " ".join(parts)
