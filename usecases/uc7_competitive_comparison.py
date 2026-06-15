"""Sheet UC7 — Competitive comparison.

Compare your app against its same-category rivals on the measurable, free signals
— category rank, overall rating, ratings volume, price, current version — then an
LLM renders a positioning read (who leads each dimension, where you're ahead /
behind, the key gap). Distinct from UC8 (which mines competitor *reviews* for
pain points) and UC2 (single-app sentiment).

It also adds a **recent-release / changelog** dimension: each app's latest-version
store changelog (Google Play ``recentChanges`` / App Store release notes) plus its
last-update date, so the report shows who is shipping most actively and what
features rivals just released. The store exposes only the *current* version's
notes (no free per-version history — see deferred UC5), so this is a snapshot of
the latest release, not a full roadmap.

Competitor discovery is iOS & free and **keyword-first**: it searches the store
for the app's theme keywords (e.g. "fps zombie" from "DEAD TARGET: FPS Zombie
Games") and keeps same-category hits — surfacing same-*theme* rivals rather than
the broad genre chart's casual toppers (Roblox/Fortnite for any game). It falls
back to the App Store genre chart (via CAP_CATEGORY) only when too few keyword
rivals are found. Pass an explicit ``competitors`` list to target specific apps
or cover Android (metadata compares fine; chart rank is iOS-only).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from connectors.base import CAP_CATEGORY, CAP_METADATA, CAP_SEARCH, ConnectorError
from core.lang import detect_lang, lang_name, market_for
from usecases.base import UseCase, resolve_app

_DEFAULT_TOP_N = 4

# Generic title words that carry no theme signal — dropped when deriving the
# keyword search for competitor discovery (so "DEAD TARGET: FPS Zombie Games"
# searches "dead target fps zombie", surfacing same-theme rivals).
_GENERIC_WORDS = {
    "game", "games", "app", "apps", "free", "the", "and", "mobile", "online",
    "offline", "pro", "hd", "plus", "lite", "3d", "2d", "new", "play", "fun",
    "best", "official", "io", "for",
}


def _keywords(title: str) -> list[str]:
    """Theme keywords from an app title (lowercased, punctuation-split, generic
    words removed). Keeps unicode letters so non-English titles still yield terms."""
    toks = re.sub(r"[\W_]+", " ", (title or "").lower(), flags=re.UNICODE).split()
    return [t for t in toks if len(t) >= 2 and t not in _GENERIC_WORDS]


def _compare_sort_key(r: dict) -> tuple:
    """Comparison-table priority: category rank (best/lowest first), then ratings
    volume (most first), then star rating (highest first). A missing value sorts
    last within its tier so apps with full data lead. Applies to apps and games."""
    rank, rc, rt = r.get("rank"), r.get("ratings_count"), r.get("rating")
    return (
        rank is None, rank if rank is not None else 0,   # 1) rank ascending, n/a last
        rc is None, -(rc or 0),                          # 2) ratings_count descending
        rt is None, -(rt or 0),                          # 3) rating descending
    )


class CompetitiveComparisonUseCase(UseCase):
    name = "uc7_competitive_comparison"
    description = (
        "Compare an app head-to-head with its same-category rivals on category rank, "
        "rating, ratings volume, price and version, PLUS recent release activity — each "
        "app's latest store changelog (release notes) and last-update date, showing who "
        "ships most actively and what features rivals just released. Gives a positioning "
        "read of who leads where, the key gaps and the biggest feature opportunity. Use "
        "for 'so sánh X với đối thủ', 'X vs Y', 'app nào mạnh hơn', 'ai dẫn đầu nhóm', "
        "'đối thủ vừa cập nhật/ra tính năng gì', 'so sánh changelog/bản cập nhật', "
        "'competitive comparison / positioning / what competitors shipped'. NOT for "
        "mining competitor complaints (that is uc8_competitor_weakness) or one app's "
        "reviews (uc2_reviews_sentiment)."
    )
    input_schema = {
        "app": "your app (name or store id)",
        "store": "ios (free rank+discovery); android compares metadata only, needs a competitors list",
        "country": "two-letter store country (default from language)",
        "competitors": "optional explicit list of competitor app names/ids",
        "top_n": "number of competitors to compare (default 4)",
        # No new input — changelog comparison uses each app's latest release notes,
        # which come back with metadata on both stores.
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
        if me.country and me.country != country:
            notes.append(f"App not found in '{country}' store — resolved on '{me.country}' instead.")
            country = me.country  # compare rivals in the same store the app was found in
        meta_conn = deps.connector_for(CAP_METADATA, store)
        if meta_conn is None:
            return {"use_case": self.name, "error": f"no metadata source for {store}"}

        rank_map: dict[str, int] = {}
        # Cache of metadata fetched during discovery, reused when building rows so
        # keyword-matched rivals aren't fetched twice.
        meta_cache: dict[str, object] = {}
        try:
            my_meta = meta_conn.get_metadata(me.app_id, store, country=country, lang=review_lang)
        except ConnectorError as exc:
            return {"use_case": self.name, "error": f"metadata fetch failed: {exc}"}
        meta_cache[me.app_id] = my_meta

        rivals = self._rivals(params.get("competitors"), me, my_meta, store, deps,
                              country, review_lang, top_n, rank_map, meta_cache, notes)
        if isinstance(rivals, dict):
            return rivals

        # Fetch metadata for every app to compare (you + rivals), concurrently.
        targets = [(me.app_id, True)] + [(r.app_id, False) for r in rivals]

        def row(app_id, is_you) -> Optional[dict]:
            m = meta_cache.get(app_id)
            if m is None:
                try:
                    m = meta_conn.get_metadata(app_id, store, country=country, lang=review_lang)
                except ConnectorError:
                    return None
            rel = m.current_version_release_date
            return {
                "name": m.name, "app_id": app_id, "is_you": is_you,
                "rank": rank_map.get(app_id),
                "rating": round(m.avg_rating, 2) if m.avg_rating is not None else None,
                "ratings_count": m.rating_count,
                "price": m.price, "version": m.version, "category": m.category,
                # Recent-release signals: the latest version's changelog (store
                # serves only the current version's notes — no free full history)
                # plus when it shipped. Powers the changelog/roadmap comparison.
                "release_date": rel.date().isoformat() if rel else None,
                "release_notes": ((m.release_notes or "").strip()[:600] or None),
            }

        with ThreadPoolExecutor(max_workers=min(5, len(targets))) as ex:
            rows = [r for r in ex.map(lambda t: row(*t), targets) if r]
        if len(rows) < 2:
            return {"use_case": self.name, "error": "not enough apps to compare", "notes": notes}

        # Order the comparison by priority — rank, then ratings volume, then stars —
        # so the table/chart read top-down by competitive standing (apps & games).
        rows.sort(key=_compare_sort_key)

        leaders = self._leaders(rows)
        positioning = self._positioning(rows, leaders, deps, notes, lang)
        changelog = self._changelog(rows, deps, notes, lang)

        result = {
            "use_case": self.name,
            "lang": lang,
            "app": {"app_id": me.app_id, "name": my_meta.name, "store": store, "category": my_meta.category},
            "comparison": rows,
            "leaders": leaders,
            "positioning": positioning,
            "changelog": changelog,
            "notes": notes,
        }
        result["summary"] = self._summarise(result, lang)
        return result

    # ------------------------------------------------------------------
    def _rivals(self, provided, me, my_meta, store, deps, country, review_lang, top_n, rank_map, meta_cache, notes):
        if provided:
            out = []
            for c in (provided if isinstance(provided, list) else [provided]):
                ref = resolve_app(str(c), store, deps, country, review_lang)
                if ref and ref.app_id and ref.app_id != me.app_id:
                    out.append(ref)
            # rank_map stays empty for an explicit list → ranks show as n/a.
            notes.append("Category rank is shown only for chart-discovered competitors.")
            return out[:top_n]

        # Keyword-first: same-theme rivals (e.g. "fps zombie") beat same-broad-genre
        # chart toppers. Fall back to the genre chart only if too few are found.
        kw_rivals = self._keyword_rivals(me, my_meta, store, deps, country, review_lang, top_n, meta_cache)
        if len(kw_rivals) >= 2:
            kws = _keywords(my_meta.name)[:5]
            notes.append(
                f"Đối thủ tìm theo từ khoá/chủ đề ({', '.join(kws)}), lọc cùng nhóm '{my_meta.category}'."
                if review_lang and review_lang.startswith("vi") else
                f"Rivals found by theme keywords ({', '.join(kws)}), filtered to '{my_meta.category}'."
            )
            self._fill_genre_ranks(my_meta.genre_id, store, deps, country, review_lang, rank_map)
            return kw_rivals

        cat_conn = deps.connector_for(CAP_CATEGORY, store)
        if cat_conn is None or not my_meta.genre_id:
            return {"use_case": self.name, "error": (
                f"no free competitor discovery for {store} — pass a 'competitors' list"
                if store == "android" else
                "could not determine category — pass a 'competitors' list")}
        notes.append("Ít đối thủ cùng từ khoá — dùng xếp hạng cùng thể loại."
                     if review_lang and review_lang.startswith("vi") else
                     "Few same-keyword rivals — falling back to the genre chart.")
        try:
            chart = cat_conn.category_apps(my_meta.genre_id, store, country=country, lang=review_lang, limit=top_n + 8)
        except ConnectorError as exc:
            return {"use_case": self.name, "error": f"category discovery failed: {exc}"}
        for pos, ref in enumerate(chart, start=1):
            rank_map[ref.app_id] = pos  # category rank = position in the genre chart
        rivals = [ref for ref in chart if ref.app_id != me.app_id][:top_n]
        return rivals

    def _keyword_rivals(self, me, my_meta, store, deps, country, lang, top_n, meta_cache):
        """Discover rivals by searching the store for the app's theme keywords, then
        keeping only same-category hits. Returns [] when no search source, no usable
        keywords, or too few same-category matches (caller then falls back to genre)."""
        search_conn = deps.connector_for(CAP_SEARCH, store)
        meta_conn = deps.connector_for(CAP_METADATA, store)
        if search_conn is None or meta_conn is None:
            return []
        kws = _keywords(my_meta.name)
        if not kws:
            return []
        try:
            hits = search_conn.search_app(" ".join(kws[:5]), store, country=country, lang=lang)
        except ConnectorError:
            return []
        # Distinct candidates excluding the app itself.
        cand, seen = [], {me.app_id}
        for h in hits:
            if h.app_id and h.app_id not in seen:
                seen.add(h.app_id)
                cand.append(h)
        cand = cand[: max(top_n * 3, top_n + 6)]
        if not cand:
            return []

        def fetch(ref):
            try:
                return ref, meta_conn.get_metadata(ref.app_id, store, country=country, lang=lang)
            except ConnectorError:
                return ref, None

        with ThreadPoolExecutor(max_workers=min(6, len(cand))) as ex:
            fetched = list(ex.map(fetch, cand))

        target_cat = (my_meta.category or "").strip().lower()
        rivals = []
        for ref, m in fetched:
            if m is None:
                continue
            meta_cache[ref.app_id] = m  # reuse when building rows
            if target_cat and (m.category or "").strip().lower() != target_cat:
                continue  # off-category (e.g. a sticker pack for a shooter) — drop
            rivals.append(ref)
            if len(rivals) >= top_n:
                break
        return rivals

    def _fill_genre_ranks(self, genre_id, store, deps, country, lang, rank_map):
        """Best-effort category rank for keyword-discovered rivals: map each app's
        position in the genre chart. Silent on failure (ranks just show n/a)."""
        cat_conn = deps.connector_for(CAP_CATEGORY, store)
        if cat_conn is None or not genre_id:
            return
        try:
            chart = cat_conn.category_apps(genre_id, store, country=country, lang=lang, limit=100)
        except ConnectorError:
            return
        for pos, ref in enumerate(chart, start=1):
            rank_map.setdefault(ref.app_id, pos)

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
            # ISO dates sort lexically → most recent first. Who shipped last.
            "recently_updated": best("release_date", True),
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

    def _changelog(self, rows, deps, notes, lang) -> dict:
        """Compare what each app shipped in its latest update (store changelog).

        Deterministic part: rank apps by recency of their last update. LLM part:
        read each app's latest-version notes and surface the feature themes rivals
        are shipping and the biggest gap/opportunity for [YOU]. The store only
        serves the *current* version's notes (no free per-version history), so this
        is a snapshot of the most recent release, not a full roadmap.
        """
        with_notes = [r for r in rows if r.get("release_notes")]
        # Recency table is always factual; never depends on the LLM or on notes text.
        recency = sorted(
            (r for r in rows if r.get("release_date")),
            key=lambda r: r["release_date"], reverse=True,
        )
        out = {
            "recency": [
                {"name": r["name"], "is_you": r["is_you"],
                 "version": r.get("version"), "release_date": r["release_date"]}
                for r in recency
            ],
            "insights": [],
        }
        if len(with_notes) < 2:
            notes.append("Changelog comparison skipped (fewer than 2 apps expose release notes).")
            return out

        you = next((r["name"] for r in rows if r["is_you"]), "our app")
        block = "\n\n".join(
            f"{'[YOU] ' if r['is_you'] else ''}{r['name']} (v{r.get('version') or '?'}, "
            f"updated {r.get('release_date') or 'unknown'}):\n{r['release_notes']}"
            for r in with_notes
        )
        prompt = (
            "You are a competitive product analyst. Below are the latest store "
            "changelogs (release notes of the current version) for our app (marked "
            f"[YOU]) and same-category rivals. For '{you}', give 3-5 concise insights: "
            "what features/themes competitors shipped recently, who is releasing most "
            "actively, and the single biggest feature gap or opportunity for us. Base "
            "every claim only on the notes below; do not invent features. "
            f"Write the insights in {lang_name(lang)}. Return ONLY JSON: "
            '{"insights": ["...", "..."]}.\n\n' + block
        )
        try:
            data = deps.llm.complete_json(prompt)
        except Exception as exc:  # noqa: BLE001 - LLM optional; degrade cleanly
            notes.append(f"Changelog narrative skipped (LLM unavailable: {exc}).")
            return out
        ins = data.get("insights") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        out["insights"] = [str(x) for x in (ins or [])][:5]
        return out

    def _summarise(self, result: dict, lang: str) -> str:
        L = result["leaders"]
        you = result["app"]["name"]
        n = len(result["comparison"]) - 1
        if lang == "vi":
            return (f"So sánh {you} với {n} đối thủ nhóm {result['app'].get('category') or '?'}. "
                    f"Dẫn đầu — rating: {L.get('rating')}, rank: {L.get('rank')}, "
                    f"quy mô (lượt rating): {L.get('ratings_count')}, "
                    f"cập nhật gần nhất: {L.get('recently_updated')}.")
        return (f"Compared {you} with {n} {result['app'].get('category') or '?'} rivals. "
                f"Leaders — rating: {L.get('rating')}, rank: {L.get('rank')}, "
                f"scale (ratings): {L.get('ratings_count')}, "
                f"most recently updated: {L.get('recently_updated')}.")
