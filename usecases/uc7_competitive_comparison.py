"""Sheet UC7 — Competitive comparison.

Compare your app against its same-category rivals on the measurable, free signals
— category rank, overall rating, ratings volume, price, current version — then an
LLM renders a positioning read (who leads each dimension, where you're ahead /
behind, the key gap). Distinct from UC8 (which mines competitor *reviews* for
pain points) and UC2 (single-app sentiment).

Competitor discovery is iOS & free (the App Store genre chart, via CAP_CATEGORY).
Pass an explicit ``competitors`` list to target specific apps or cover Android
(metadata compares fine; chart rank is iOS-only).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from connectors.base import CAP_CATEGORY, CAP_METADATA, ConnectorError
from core.lang import detect_lang, lang_name, market_for
from usecases.base import UseCase, resolve_app

_DEFAULT_TOP_N = 4


class CompetitiveComparisonUseCase(UseCase):
    name = "uc7_competitive_comparison"
    description = (
        "Compare an app head-to-head with its same-category rivals on category rank, "
        "rating, ratings volume, price and version, with a positioning read of who leads "
        "where and the key gaps. Use for 'so sánh X với đối thủ', 'X vs Y', 'app nào "
        "mạnh hơn', 'ai dẫn đầu nhóm', 'competitive comparison / positioning'. NOT for "
        "mining competitor complaints (that is uc8_competitor_weakness) or one app's "
        "reviews (uc2_reviews_sentiment)."
    )
    input_schema = {
        "app": "your app (name or store id)",
        "store": "ios (free rank+discovery); android compares metadata only, needs a competitors list",
        "country": "two-letter store country (default from language)",
        "competitors": "optional explicit list of competitor app names/ids",
        "top_n": "number of competitors to compare (default 4)",
    }

    def run(self, params: dict, deps, context=None) -> dict:
        app_query = (params.get("app") or "").strip()
        if not app_query:
            return {"use_case": self.name, "error": "missing 'app' parameter"}
        lang = (params.get("lang") or detect_lang(app_query)).lower()
        market_country, review_lang = market_for(lang)
        country = params.get("country") or market_country
        top_n = int(params.get("top_n", _DEFAULT_TOP_N) or _DEFAULT_TOP_N)
        store = (params.get("store") or "ios").lower()
        if store in ("both", "all", "cross", "cross_platform"):
            store = "ios"
        notes: list[str] = []

        me = resolve_app(app_query, store, deps, country, review_lang)
        if me is None or not me.app_id:
            return {"use_case": self.name, "error": f"could not resolve app '{app_query}' on {store}"}
        meta_conn = deps.connector_for(CAP_METADATA, store)
        if meta_conn is None:
            return {"use_case": self.name, "error": f"no metadata source for {store}"}

        # Genre chart gives both the competitor set AND each app's category rank (its
        # position in the ordered list). One fetch, reused as a rank map.
        rank_map: dict[str, int] = {}
        my_genre = None
        try:
            my_meta = meta_conn.get_metadata(me.app_id, store, country=country, lang=review_lang)
            my_genre = my_meta.genre_id
        except ConnectorError as exc:
            return {"use_case": self.name, "error": f"metadata fetch failed: {exc}"}

        rivals = self._rivals(params.get("competitors"), me, my_genre, store, deps,
                              country, review_lang, top_n, rank_map, notes)
        if isinstance(rivals, dict):
            return rivals

        # Fetch metadata for every app to compare (you + rivals), concurrently.
        targets = [(me.app_id, True)] + [(r.app_id, False) for r in rivals]

        def row(app_id, is_you) -> Optional[dict]:
            try:
                m = my_meta if (is_you and app_id == me.app_id) else \
                    meta_conn.get_metadata(app_id, store, country=country, lang=review_lang)
            except ConnectorError:
                return None
            return {
                "name": m.name, "app_id": app_id, "is_you": is_you,
                "rank": rank_map.get(app_id),
                "rating": round(m.avg_rating, 2) if m.avg_rating is not None else None,
                "ratings_count": m.rating_count,
                "price": m.price, "version": m.version, "category": m.category,
            }

        with ThreadPoolExecutor(max_workers=min(5, len(targets))) as ex:
            rows = [r for r in ex.map(lambda t: row(*t), targets) if r]
        if len(rows) < 2:
            return {"use_case": self.name, "error": "not enough apps to compare", "notes": notes}

        leaders = self._leaders(rows)
        positioning = self._positioning(rows, leaders, deps, notes, lang)

        result = {
            "use_case": self.name,
            "lang": lang,
            "app": {"app_id": me.app_id, "name": my_meta.name, "store": store, "category": my_meta.category},
            "comparison": rows,
            "leaders": leaders,
            "positioning": positioning,
            "notes": notes,
        }
        result["summary"] = self._summarise(result, lang)
        return result

    # ------------------------------------------------------------------
    def _rivals(self, provided, me, genre_id, store, deps, country, review_lang, top_n, rank_map, notes):
        if provided:
            out = []
            for c in (provided if isinstance(provided, list) else [provided]):
                ref = resolve_app(str(c), store, deps, country, review_lang)
                if ref and ref.app_id and ref.app_id != me.app_id:
                    out.append(ref)
            # rank_map stays empty for an explicit list → ranks show as n/a.
            notes.append("Category rank is shown only for chart-discovered competitors.")
            return out[:top_n]

        cat_conn = deps.connector_for(CAP_CATEGORY, store)
        if cat_conn is None or not genre_id:
            return {"use_case": self.name, "error": (
                f"no free competitor discovery for {store} — pass a 'competitors' list"
                if store == "android" else
                "could not determine category — pass a 'competitors' list")}
        try:
            chart = cat_conn.category_apps(genre_id, store, country=country, lang=review_lang, limit=top_n + 8)
        except ConnectorError as exc:
            return {"use_case": self.name, "error": f"category discovery failed: {exc}"}
        for pos, ref in enumerate(chart, start=1):
            rank_map[ref.app_id] = pos  # category rank = position in the genre chart
        rivals = [ref for ref in chart if ref.app_id != me.app_id][:top_n]
        return rivals

    def _leaders(self, rows: list[dict]) -> dict:
        def best(key, reverse):
            vals = [r for r in rows if r.get(key) is not None]
            if not vals:
                return None
            return sorted(vals, key=lambda r: r[key], reverse=reverse)[0]["name"]
        return {
            "rating": best("rating", True),
            "rank": best("rank", False),       # lower rank number = better
            "ratings_count": best("ratings_count", True),
        }

    def _positioning(self, rows, leaders, deps, notes, lang) -> list[str]:
        table = "\n".join(
            f"- {'[YOU] ' if r['is_you'] else ''}{r['name']}: rank={r.get('rank')}, "
            f"rating={r.get('rating')} ({r.get('ratings_count')} ratings), price={r.get('price')}, "
            f"version={r.get('version')}"
            for r in rows
        )
        you = next((r["name"] for r in rows if r["is_you"]), "our app")
        prompt = (
            "You are a competitive analyst. Below is a comparison of our app (marked [YOU]) "
            f"against same-category rivals. Give 3-5 concise positioning insights for '{you}': "
            "who leads on rating / category rank / scale (ratings count), where we are ahead or "
            "behind, and the single biggest gap or opportunity. "
            f"Write the insights in {lang_name(lang)}. Return ONLY JSON: "
            '{"insights": ["...", "..."]}.\n\n' + table
        )
        try:
            data = deps.llm.complete_json(prompt)
        except Exception as exc:  # noqa: BLE001 - LLM optional; degrade cleanly
            notes.append(f"Positioning narrative skipped (LLM unavailable: {exc}).")
            return []
        ins = data.get("insights") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return [str(x) for x in (ins or [])][:5]

    def _summarise(self, result: dict, lang: str) -> str:
        L = result["leaders"]
        you = result["app"]["name"]
        n = len(result["comparison"]) - 1
        if lang == "vi":
            return (f"So sánh {you} với {n} đối thủ nhóm {result['app'].get('category') or '?'}. "
                    f"Dẫn đầu — rating: {L.get('rating')}, rank: {L.get('rank')}, "
                    f"quy mô (lượt rating): {L.get('ratings_count')}.")
        return (f"Compared {you} with {n} {result['app'].get('category') or '?'} rivals. "
                f"Leaders — rating: {L.get('rating')}, rank: {L.get('rank')}, "
                f"scale (ratings): {L.get('ratings_count')}.")
