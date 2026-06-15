"""Sheet UC8 — Competitor weakness mining.

For your app's same-category rivals: pull their NEGATIVE reviews, cluster the
recurring pain points (bugs, missing features, monetization/UX complaints) across
competitors, and turn them into a PRIORITISED opportunity list with evidence —
where rivals are weak is where you can win.

Competitor discovery is iOS & free (the App Store genre top-free chart, via the
``category`` capability). Pass an explicit ``competitors`` list to target specific
apps or to cover Android (which has no free category listing).

Reuses: resolve_app, the category + reviews connectors, and the LLM — no
greennode-agentbase import, so it is unit-testable against live data.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

from connectors.base import CAP_CATEGORY, CAP_METADATA, CAP_REVIEWS, ConnectorError
from core.lang import detect_lang, lang_name, market_for
from usecases.base import UseCase, resolve_app

_SAMPLE_PER_APP = 8       # negatives per competitor sent to the LLM (bounds the prompt)
_DEFAULT_TOP_N = 4
_NEG_RATING = 2           # rating <= this counts as a negative/pain-point review


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class CompetitorWeaknessUseCase(UseCase):
    name = "uc8_competitor_weakness"
    description = (
        "Mine COMPETITOR weaknesses into opportunities. For an app's same-category rivals, "
        "cluster their negative-review pain points (bugs, missing features, monetization/UX "
        "complaints) into a prioritised opportunity list with evidence quotes. Use for "
        "'đối thủ cùng category bị chê gì', 'điểm yếu đối thủ', 'cơ hội từ đối thủ', "
        "'competitor weakness / pain points'. Competitor discovery is iOS; pass a competitors "
        "list for Android or to target specific apps."
    )
    input_schema = {
        "app": "your app (name or store id)",
        "store": "ios (free competitor discovery); android requires a 'competitors' list",
        "country": "two-letter store country (default from language)",
        "competitors": "optional explicit list of competitor app names/ids",
        "window_days": "review window in days (default 60)",
        "top_n": "number of competitors to mine (default 4)",
    }

    def run(self, params: dict, deps, context=None) -> dict:
        app_query = (params.get("app") or "").strip()
        if not app_query:
            return {"use_case": self.name, "error": "missing 'app' parameter"}

        lang = (params.get("lang") or detect_lang(app_query)).lower()
        market_country, review_lang = market_for(lang)
        country = params.get("country") or market_country
        window_days = int(params.get("window_days", 60) or 60)
        top_n = int(params.get("top_n", _DEFAULT_TOP_N) or _DEFAULT_TOP_N)
        store = (params.get("store") or "ios").lower()
        if store in ("both", "all", "cross", "cross_platform"):
            store = "ios"  # competitor discovery is iOS-only on free sources
        notes: list[str] = []

        # 1. Resolve your app + its category/genre.
        me = resolve_app(app_query, store, deps, country, review_lang)
        if me is None or not me.app_id:
            return {"use_case": self.name, "error": f"could not resolve app '{app_query}' on {store}"}
        my_name, genre_id, category = me.name, None, None
        meta_conn = deps.connector_for(CAP_METADATA, store)
        if meta_conn is not None:
            try:
                m = meta_conn.get_metadata(me.app_id, store, country=country, lang=review_lang)
                my_name, genre_id, category = (m.name or my_name), m.genre_id, m.category
            except ConnectorError:
                pass

        # 2. Discover competitors — explicit list wins; else the genre chart (iOS).
        competitors = self._competitors(params.get("competitors"), me, genre_id, store,
                                        deps, country, review_lang, top_n)
        if isinstance(competitors, dict):  # an error dict
            return competitors
        if not competitors:
            return {"use_case": self.name, "error": "no competitors found", "notes": notes}

        # 3. Negative reviews per competitor (concurrent — I/O bound).
        end = datetime.utcnow()
        start = end - timedelta(days=window_days)
        review_conns = deps.connectors_for(CAP_REVIEWS, store)
        if not review_conns:
            return {"use_case": self.name, "error": f"no review source for {store}"}

        def fetch_negs(ref) -> dict:
            errs = []
            for conn in review_conns:
                try:
                    rs = conn.get_reviews(ref.app_id, store, start, end, country=country, lang=review_lang)
                    neg = [r for r in rs if r.rating is not None and r.rating <= _NEG_RATING
                           and (r.content or "").strip()]
                    return {"app_id": ref.app_id, "name": ref.name, "neg_count": len(neg),
                            "total": len(rs), "sample": neg[:_SAMPLE_PER_APP]}
                except ConnectorError as exc:
                    errs.append(f"{conn.name}: {exc}")
            return {"app_id": ref.app_id, "name": ref.name, "neg_count": 0, "total": 0,
                    "sample": [], "error": "; ".join(errs)}

        with ThreadPoolExecutor(max_workers=min(4, len(competitors))) as ex:
            comp_data = list(ex.map(fetch_negs, competitors))

        # 4. Cluster pain points across competitors → opportunities (one LLM call).
        opportunities = self._mine(comp_data, my_name, deps, notes, lang)

        result = {
            "use_case": self.name,
            "lang": lang,
            "app": {"app_id": me.app_id, "name": my_name, "store": store, "category": category},
            "window": {"from": start.date().isoformat(), "to": end.date().isoformat(), "days": window_days},
            "competitors": [
                {"name": c["name"], "app_id": c["app_id"],
                 "negative_reviews": c["neg_count"], "reviews_fetched": c["total"]}
                for c in comp_data
            ],
            "opportunities": opportunities,
            "notes": notes,
        }
        result["summary"] = self._summarise(result, lang)
        return result

    # ------------------------------------------------------------------
    def _competitors(self, provided, me, genre_id, store, deps, country, review_lang, top_n):
        """Resolve an explicit competitor list, else discover via the genre chart.
        Returns a list of AppRef, or an error dict."""
        out = []
        if provided:
            for c in (provided if isinstance(provided, list) else [provided]):
                ref = resolve_app(str(c), store, deps, country, review_lang)
                if ref and ref.app_id and ref.app_id != me.app_id:
                    out.append(ref)
            return out[:max(top_n, len(out))]

        cat_conn = deps.connector_for(CAP_CATEGORY, store)
        if cat_conn is None or not genre_id:
            return {"use_case": self.name, "error": (
                f"no free competitor discovery for {store} — pass a 'competitors' list"
                if store == "android" else
                "could not determine category for the app — pass a 'competitors' list")}
        try:
            refs = cat_conn.category_apps(genre_id, store, country=country, lang=review_lang, limit=top_n + 6)
        except ConnectorError as exc:
            return {"use_case": self.name, "error": f"category discovery failed: {exc}"}
        for r in refs:
            if r.app_id != me.app_id:
                out.append(r)
            if len(out) >= top_n:
                break
        return out

    def _mine(self, comp_data: list[dict], my_name: str, deps, notes: list[str], lang: str) -> list[dict]:
        blocks = []
        for c in comp_data:
            if c.get("sample"):
                lines = "\n".join(f"  - ({r.rating}★) {r.content[:240]}" for r in c["sample"])
                blocks.append(f"[{c['name']}] ({c['neg_count']} negative reviews)\n{lines}")
        if not blocks:
            notes.append("No negative competitor reviews found in the window — nothing to mine.")
            return []
        prompt = (
            "You are a product strategist. Below are NEGATIVE reviews of competitor apps. "
            f"Cluster the recurring pain points across them into OPPORTUNITIES for our app ('{my_name}'). "
            "Return ONLY JSON: a list of objects "
            '{"theme": str, "category": "bug|missing_feature|monetization|ux|performance|support|other", '
            '"count": int (reviews mentioning it), "competitors": [affected app names], '
            '"opportunity": "one line on how our app can win here", '
            '"examples": [up to 2 verbatim quotes, each a COMPLETE phrase — never cut mid-word]}, '
            "sorted by count descending, top 6. "
            f"Write the 'theme' and 'opportunity' text in {lang_name(lang)} (keep 'category' as the "
            "English enum value). Keep example quotes verbatim in their original language.\n\n"
            + "\n\n".join(blocks)
        )
        try:
            data = deps.llm.complete_json(prompt)
        except Exception as exc:  # noqa: BLE001 - LLM optional; degrade cleanly
            notes.append(f"Pain-point clustering skipped (LLM unavailable: {exc}).")
            return []
        if isinstance(data, dict):
            data = data.get("opportunities") or data.get("themes") or []
        out = []
        for it in data if isinstance(data, list) else []:
            if isinstance(it, dict) and it.get("theme"):
                out.append({
                    "theme": it.get("theme"),
                    "category": it.get("category"),
                    "count": it.get("count", 0),
                    "competitors": (it.get("competitors") or [])[:6],
                    "opportunity": it.get("opportunity"),
                    "examples": (it.get("examples") or [])[:2],
                })
        return out[:6]

    def _summarise(self, result: dict, lang: str) -> str:
        n = len(result["competitors"])
        cat = result["app"].get("category") or "?"
        opps = result.get("opportunities", [])
        top = ", ".join(o.get("theme", "?") for o in opps[:3])
        if lang == "vi":
            parts = [f"Khai thác {n} đối thủ cùng nhóm {cat} của {result['app']['name']}."]
            parts.append(f"Cơ hội hàng đầu: {top}." if top else "Chưa tìm thấy điểm yếu nổi bật trong cửa sổ.")
        else:
            parts = [f"Mined {n} same-category ({cat}) rivals of {result['app']['name']}."]
            parts.append(f"Top opportunities: {top}." if top else "No standout weaknesses found in the window.")
        return " ".join(parts)
