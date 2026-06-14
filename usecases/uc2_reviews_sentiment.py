"""Sheet UC2 — Crawl reviews & sentiment.

For any app over a time window: crawl reviews from both stores, then report
volume, star distribution, language mix, star-derived sentiment, a weekly trend,
and LLM-clustered themes (praise vs complaint/bug). Persists the raw review table
for downstream use cases (weakness mining, dashboards).

Sentiment is star-derived (1–2 negative / 3 neutral / 4–5 positive) for every
review — cheap, deterministic, no LLM timeout risk; the LLM is used only to
cluster themes on a bounded sample. Single-app (iOS+Android); competitor
comparison is UC7/UC8.

Limits: language detection is vi/en only (core.lang); App Store recent-review
depth is RSS-bound (~1 month for busy apps).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from connectors.base import CAP_METADATA, CAP_REVIEWS, ConnectorError, Review
from core.lang import detect_lang, market_for
from usecases.base import UseCase, resolve_app

# Bounded sample sizes for the single LLM theme-clustering call. Kept small so the
# (sometimes slow) MaaS model answers inside the LLM timeout — see core/llm.py.
_SAMPLE_PER_POLARITY = 8


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _pct(count: int, total: int) -> float:
    return round(100.0 * count / total, 1) if total else 0.0


class ReviewsSentimentUseCase(UseCase):
    name = "uc2_reviews_sentiment"
    description = (
        "Describe/measure user reviews over a time window — volume, star distribution, "
        "language mix, sentiment, weekly trend, and praise/complaint theme clusters. "
        "Answers 'what are users saying / how is sentiment'. Reports WHAT users say; does "
        "NOT test a cause-effect hypothesis (use hypothesis_check for 'X is due to Y')."
    )
    input_schema = {
        "app": "app name to search, or a store id (iOS trackId / Android package)",
        "store": "ios | android | both (default both)",
        "country": "two-letter store country (default from language)",
        "window_days": "size of the recent window in days (default 30)",
        "date_from": "ISO start (overrides window_days when both dates given)",
        "date_to": "ISO end (overrides window_days when both dates given)",
    }

    def run(self, params: dict, deps, context=None) -> dict:
        store = (params.get("store") or "both").lower()
        app_query = (params.get("app") or "").strip()
        if not app_query:
            return {"use_case": self.name, "error": "missing 'app' parameter"}

        lang = (params.get("lang") or detect_lang(app_query)).lower()
        market_country, review_lang = market_for(lang)
        country = params.get("country") or market_country
        start, end = self._window(params)

        if app_query.isdigit():
            store = "ios"

        if store in ("both", "all", "cross", "cross_platform"):
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=2) as ex:
                futures = {
                    s: ex.submit(self._analyze_one, app_query, s, country, review_lang, lang, start, end, deps)
                    for s in ("ios", "android")
                }
                platforms = {s: f.result() for s, f in futures.items()}
            return {
                "use_case": self.name,
                "mode": "cross_platform",
                "lang": lang,
                "app_query": app_query,
                "window": {"from": start.date().isoformat(), "to": end.date().isoformat()},
                "platforms": platforms,
            }
        return self._analyze_one(app_query, store, country, review_lang, lang, start, end, deps)

    def _window(self, params: dict) -> tuple[datetime, datetime]:
        end = datetime.utcnow()
        df, dt = params.get("date_from"), params.get("date_to")
        if df and dt:
            try:
                return (_naive(datetime.fromisoformat(str(df))),
                        _naive(datetime.fromisoformat(str(dt))))
            except ValueError:
                pass  # fall back to window_days
        days = int(params.get("window_days", 30) or 30)
        return end - timedelta(days=days), end

    def _analyze_one(self, app_query, store, review_lang, lang, out_lang, start, end, deps) -> dict:
        notes: list[str] = []
        app_ref = resolve_app(app_query, store, deps, review_lang, review_lang)
        if app_ref is None or not app_ref.app_id:
            return {"use_case": self.name, "error": f"could not resolve app '{app_query}' on {store}"}

        # When resolved by a raw store id the name == id; fetch the real name (best-effort).
        display_name = app_ref.name
        if display_name == app_ref.app_id:
            meta_conn = deps.connector_for(CAP_METADATA, store)
            if meta_conn is not None:
                try:
                    display_name = meta_conn.get_metadata(
                        app_ref.app_id, store, country=review_lang, lang=review_lang
                    ).name or display_name
                except ConnectorError:
                    pass

        review_conns = deps.connectors_for(CAP_REVIEWS, store)
        if not review_conns:
            return {
                "use_case": self.name,
                "error": f"no review source for {store}",
            }
        reviews: list[Review] = []
        review_source = None
        review_errors: list[str] = []  # only surfaced if ALL sources fail (silent fallback)
        for conn in review_conns:
            try:
                reviews = conn.get_reviews(app_ref.app_id, store, start, end, country=review_lang, lang=review_lang)
                review_source = conn.name
                break
            except ConnectorError as exc:
                review_errors.append(f"{conn.name}: {exc}")
        if review_source is None:
            return {"use_case": self.name,
                    "error": f"all review sources failed for {store} ({'; '.join(review_errors)})"}

        # Defensive window clamp (connectors already filter, but be safe).
        in_window = [r for r in reviews if (rd := _naive(r.date)) and start <= rd <= end]

        stats = self._statistics(in_window)
        themes = self._cluster_themes(in_window, deps, notes, out_lang)
        sample = [
            {
                "date": _naive(r.date).date().isoformat() if r.date else None,
                "rating": r.rating,
                "title": r.title,
                "content": (r.content or "")[:200],
                "lang": detect_lang(r.content or ""),
            }
            for r in in_window[:10]
        ]

        try:
            deps.storage.save_table(
                "reviews", app_ref.app_id, store,
                [{"date": _naive(r.date).isoformat() if r.date else None, "rating": r.rating,
                  "title": r.title, "content": r.content, "version": r.version,
                  "author": r.author, "source": r.source} for r in in_window],
                captured_at=datetime.utcnow().date().isoformat(),
            )
        except OSError as exc:
            notes.append(f"Could not persist reviews table ({exc}).")

        result = {
            "use_case": self.name,
            "lang": out_lang,
            "app": {"app_id": app_ref.app_id, "name": display_name, "store": store},
            "window": {"from": start.date().isoformat(), "to": end.date().isoformat(),
                       "days": (end - start).days},
            "review_source": review_source,
            **stats,
            "themes": themes,
            "sample_reviews": sample,
            "notes": notes,
        }
        result["summary"] = self._summarise(result, out_lang)
        return result

    # ------------------------------------------------------------ statistics
    def _statistics(self, reviews: list[Review]) -> dict:
        rated = [r for r in reviews if r.rating is not None]
        with_text = [r for r in reviews if (r.content or "").strip()]
        n_rated = len(rated)

        star = {
            str(s): {"count": (c := sum(1 for r in rated if r.rating == s)), "pct": _pct(c, n_rated)}
            for s in range(1, 6)
        }
        neg = sum(1 for r in rated if r.rating <= 2)
        neu = sum(1 for r in rated if r.rating == 3)
        pos = sum(1 for r in rated if r.rating >= 4)
        sentiment = {
            "negative": {"count": neg, "pct": _pct(neg, n_rated)},
            "neutral": {"count": neu, "pct": _pct(neu, n_rated)},
            "positive": {"count": pos, "pct": _pct(pos, n_rated)},
        }

        langs: dict[str, int] = {}
        for r in with_text:
            langs[detect_lang(r.content)] = langs.get(detect_lang(r.content), 0) + 1
        language_distribution = {
            k: {"count": v, "pct": _pct(v, len(with_text))} for k, v in sorted(langs.items())
        }

        return {
            "totals": {"reviews": len(reviews), "with_text": len(with_text), "rated": n_rated},
            "avg_rating": round(sum(r.rating for r in rated) / n_rated, 2) if n_rated else None,
            "star_distribution": star,
            "sentiment": sentiment,
            "language_distribution": language_distribution,
            "weekly_trend": self._weekly_trend(reviews),
        }

    def _weekly_trend(self, reviews: list[Review]) -> list[dict]:
        buckets: dict[str, list[Review]] = {}
        for r in reviews:
            d = _naive(r.date)
            if d is None:
                continue
            iso = d.isocalendar()
            buckets.setdefault(f"{iso[0]}-W{iso[1]:02d}", []).append(r)
        out = []
        for week in sorted(buckets):
            rs = buckets[week]
            rated = [x.rating for x in rs if x.rating is not None]
            neg = sum(1 for x in rs if x.rating is not None and x.rating <= 2)
            out.append({
                "week": week,
                "volume": len(rs),
                "avg_rating": round(sum(rated) / len(rated), 2) if rated else None,
                "negative_pct": _pct(neg, len(rated)),
            })
        return out

    # --------------------------------------------------------- theme clusters
    def _cluster_themes(self, reviews: list[Review], deps, notes: list[str], lang: str) -> dict:
        pos = [r for r in reviews if r.rating is not None and r.rating >= 4 and (r.content or "").strip()]
        neg = [r for r in reviews if r.rating is not None and r.rating <= 3 and (r.content or "").strip()]
        if not pos and not neg:
            return {"praise": [], "complaints": []}

        def fmt(rs):
            return "\n".join(f"- ({r.rating}★) {r.content[:100]}" for r in rs[:_SAMPLE_PER_POLARITY])

        prompt = (
            "You are a product analyst. Cluster these app reviews into themes.\n"
            "Return ONLY JSON: {\"praise\": [...], \"complaints\": [...]} where each item is "
            '{"theme": str, "count": int, "examples": [up to 2 short verbatim quotes]}, '
            "sorted by count descending, top 5 each. 'praise' = what users like; "
            "'complaints' = bugs / issues / dislikes. Keep quotes in their original language.\n\n"
            f"POSITIVE REVIEWS (4-5★):\n{fmt(pos) or '(none)'}\n\n"
            f"NEGATIVE/NEUTRAL REVIEWS (1-3★):\n{fmt(neg) or '(none)'}"
        )
        try:
            data = deps.llm.complete_json(prompt)
        except Exception as exc:  # noqa: BLE001 - LLM optional; degrade cleanly
            notes.append(f"Theme clustering skipped (LLM unavailable: {exc}).")
            return {"praise": [], "complaints": []}

        def clean(items):
            out = []
            for it in items if isinstance(items, list) else []:
                if isinstance(it, dict) and it.get("theme"):
                    out.append({"theme": it.get("theme"), "count": it.get("count", 0),
                                "examples": (it.get("examples") or [])[:2]})
            return out[:5]

        data = data if isinstance(data, dict) else {}
        return {"praise": clean(data.get("praise")), "complaints": clean(data.get("complaints"))}

    # ---------------------------------------------------------------- summary
    def _summarise(self, result: dict, lang: str) -> str:
        name = result["app"]["name"]
        t = result["totals"]
        s = result["sentiment"]
        avg = result.get("avg_rating")
        themes = result.get("themes", {})
        top_complaint = themes.get("complaints", [{}])[0].get("theme") if themes.get("complaints") else None
        top_praise = themes.get("praise", [{}])[0].get("theme") if themes.get("praise") else None
        if lang == "vi":
            parts = [f"{name}: {t['reviews']} review trong cửa sổ, rating TB {avg if avg is not None else 'n/a'}."]
            parts.append(f"Sentiment: {s['positive']['pct']}% tích cực / {s['negative']['pct']}% tiêu cực.")
            if top_praise:
                parts.append(f"Khen nhiều nhất: {top_praise}.")
            if top_complaint:
                parts.append(f"Phàn nàn nhiều nhất: {top_complaint}.")
        else:
            parts = [f"{name}: {t['reviews']} reviews in window, avg rating {avg if avg is not None else 'n/a'}."]
            parts.append(f"Sentiment: {s['positive']['pct']}% positive / {s['negative']['pct']}% negative.")
            if top_praise:
                parts.append(f"Top praise: {top_praise}.")
            if top_complaint:
                parts.append(f"Top complaint: {top_complaint}.")
        return " ".join(parts)
