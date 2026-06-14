"""Sheet UC6 — Version Impact (post-release health check).

For any user-chosen app: resolve it, find the latest release, pull reviews around
that release, and report whether the build looks healthy — rating movement,
review velocity, negative-share shift — plus LLM-categorised new complaints.

This is the metric-delta / before-after-release core of sheet UC6. Full UC6
("which feature drove the change") additionally needs the UC5 feature timeline;
that attribution layer is not built yet.

Pure Python + connectors + LLM; no greennode-agentbase import, so it is unit
testable against live iTunes/Google Play data without the runtime.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from connectors.base import CAP_METADATA, CAP_REVIEWS, CAP_SEARCH, ConnectorError, Review
from core.lang import detect_lang, market_for
from storage.snapshots import Snapshot
from usecases.base import UseCase

# Issue taxonomy the LLM must map complaints into.
ISSUE_CATEGORIES = [
    "crash",
    "performance",
    "ux",
    "auth",
    "payment",
    "content",
    "ads",
    "other",
]

REGRESSION_RATING_DROP = -0.2
REGRESSION_NEG_SHARE_PP = 10.0
# Overall store rating moves slowly (huge denominator), so a small snapshot-to-
# snapshot move is meaningful for the metric-only (iOS) path. A flat trend between
# these bounds is NOT a clean "healthy" — it's no signal -> inconclusive.
METRIC_RATING_DROP = -0.05
METRIC_RATING_RISE = 0.05


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalise to naive UTC so tz-aware (iTunes) and naive (Google Play) compare."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _looks_like_id(app: str, store: str) -> bool:
    if store == "ios":
        return app.isdigit()
    # android package id, e.g. com.vng.zalopay
    return bool(re.fullmatch(r"[a-zA-Z][\w.]+\.[\w.]+", app))


def _names_match(a: str, b: str) -> bool:
    """Loose match on the first alphanumeric token — catches store name variants
    (Spotify: Music vs Spotify: Music & Podcasts) while flagging real mismatches
    (Zalo vs Zalopay)."""
    def first_tok(s: str) -> str:
        toks = re.findall(r"[a-z0-9]+", s.lower())
        return toks[0] if toks else ""

    return bool(first_tok(a)) and first_tok(a) == first_tok(b)


def _avg(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _neg_share(reviews: list[Review]) -> Optional[float]:
    rated = [r for r in reviews if r.rating is not None]
    if not rated:
        return None
    neg = sum(1 for r in rated if r.rating <= 2)
    return 100.0 * neg / len(rated)


class VersionImpactUseCase(UseCase):
    name = "uc6_version_impact"
    description = (
        "Post-release health check for any app: rating movement, review velocity, "
        "and newly surfaced complaints around the latest update."
    )
    input_schema = {
        "app": "app name to search, or a store id (iOS trackId / Android package)",
        "store": "ios | android | both (default: both — analyses iOS and Android together)",
        "country": "two-letter store country (default from config)",
        "window_days": "days before the release to use as baseline (default 14)",
    }

    def run(self, params: dict, deps, context=None) -> dict:
        store = (params.get("store") or "both").lower()
        app_query = (params.get("app") or "").strip()
        if not app_query:
            return {"use_case": self.name, "error": "missing 'app' parameter"}

        # Response language + store market: auto-detected (router sets params['lang']).
        # Vietnamese -> VN store + Vietnamese reviews; English -> US store.
        lang = (params.get("lang") or detect_lang(app_query)).lower()
        market_country, _ = market_for(lang)
        country = params.get("country") or market_country
        window_days = int(params.get("window_days", 14))

        # A store-specific id only resolves on its own store → narrow a "both" request
        # so passing a package (Android) or trackId (iOS) gives a precise single-store result.
        if store in ("both", "all", "cross", "cross_platform"):
            if app_query.isdigit():
                store = "ios"
            elif _looks_like_id(app_query, "android"):
                store = "android"

        # Default: analyse BOTH stores and combine — a PM/exec cares about iOS + Android.
        if store in ("both", "all", "cross", "cross_platform"):
            # Run the two stores concurrently (I/O-bound: HTTP + scraper + LLM) so the
            # cross-platform wall-clock ~= the slower store, not the sum.
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=2) as ex:
                futures = {
                    s: ex.submit(self._analyze_one, app_query, s, country, lang, window_days, deps)
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
            # Honesty: Google Play name search is unreliable; if the two stores
            # resolved to different apps, say so rather than presenting them as one.
            names = {s: (p.get("app", {}).get("name") or "")
                     for s, p in platforms.items() if not p.get("error")}
            ios_n, and_n = names.get("ios", ""), names.get("android", "")
            if ios_n and and_n and not _names_match(ios_n, and_n):
                result["warning"] = (
                    f"⚠️ iOS resolve '{ios_n}', Android resolve '{and_n}' — có thể là 2 app khác nhau. "
                    f"Truyền package id (Android) / trackId (iOS) để chính xác."
                    if lang == "vi" else
                    f"⚠️ iOS resolved '{ios_n}', Android '{and_n}' — likely different apps. "
                    f"Pass the package id (Android) / trackId (iOS) for precision."
                )
            return result
        return self._analyze_one(app_query, store, country, lang, window_days, deps)

    def _analyze_one(self, app_query: str, store: str, country: str, lang: str, window_days: int, deps) -> dict:
        notes: list[str] = []

        # 1. RESOLVE APP --------------------------------------------------
        app_ref = self._resolve(app_query, store, deps, country, lang)
        if app_ref is None:
            return {
                "use_case": self.name,
                "error": f"could not resolve app '{app_query}' on {store}",
            }

        # 2. METADATA + RELEASE ------------------------------------------
        meta_conn = deps.connector_for(CAP_METADATA, store)
        if meta_conn is None:
            return {"use_case": self.name, "error": f"no metadata source for {store}"}
        if not app_ref.app_id:
            return {"use_case": self.name, "error": f"could not resolve '{app_query}' on {store}"}
        try:
            meta = meta_conn.get_metadata(app_ref.app_id, store, country=country, lang=lang)
        except ConnectorError as exc:
            return {"use_case": self.name, "error": f"metadata fetch failed: {exc}"}
        release_dt = _naive(meta.current_version_release_date)

        deps.storage.save(
            Snapshot(
                captured_at=datetime.utcnow().date().isoformat(),
                app_id=meta.app_id,
                store=store,
                version=meta.version,
                avg_rating=meta.avg_rating,
                rating_count=meta.rating_count,
                current_version_release_date=(
                    meta.current_version_release_date.isoformat()
                    if meta.current_version_release_date
                    else None
                ),
            )
        )

        # Metric baseline from snapshot history — the time-series signal that works
        # WITHOUT review text (e.g. iOS): compare current rating to the most recent
        # prior snapshot. Needs >= 2 runs; first run just seeds the baseline.
        history = deps.storage.history(meta.app_id, store)
        prior = history[-2] if len(history) >= 2 else None
        metric_rating_delta = None
        new_ratings_since = None
        if prior and prior.avg_rating is not None and meta.avg_rating is not None:
            metric_rating_delta = round(meta.avg_rating - prior.avg_rating, 3)
            if prior.rating_count is not None and meta.rating_count is not None:
                new_ratings_since = meta.rating_count - prior.rating_count

        app_info = {
            "app_id": meta.app_id,
            "name": meta.name,
            "store": store,
            "publisher": meta.publisher,
            "overall_avg_rating": meta.avg_rating,
            "overall_rating_count": meta.rating_count,
        }
        release_info = {
            "version": meta.version,
            "release_date": release_dt.date().isoformat() if release_dt else None,
            "release_notes": (meta.release_notes or "")[:500] or None,
        }

        if release_dt is None:
            notes.append("Release date unavailable from metadata — cannot split before/after.")
            return self._inconclusive(app_info, release_info, notes, meta_conn.name, lang)

        # 3. REVIEWS AROUND RELEASE --------------------------------------
        # Try capable connectors best-first; fall back when one errors (e.g. a
        # Sensor Tower token that lacks reviews scope -> fall through to Google Play).
        review_conns = deps.connectors_for(CAP_REVIEWS, store)
        before: list[Review] = []
        after: list[Review] = []
        review_source = None
        reviews: list[Review] = []
        if not review_conns:
            notes.append(
                f"No review-text source available for {store} "
                f"(no connector advertised the 'reviews' capability). Metrics-only report."
            )
        else:
            now = datetime.utcnow()
            start = release_dt - timedelta(days=window_days)
            for conn in review_conns:
                try:
                    reviews = conn.get_reviews(app_ref.app_id, store, start, now, country=country, lang=lang)
                    review_source = conn.name
                    break
                except ConnectorError as exc:
                    notes.append(f"{conn.name} reviews unavailable ({exc}); trying next source.")
            if review_source is None:
                notes.append("All review sources failed — metrics-only report.")
            for r in reviews:
                rd = _naive(r.date)
                if rd is None:
                    continue
                (before if rd < release_dt else after).append(r)

        # 4. SIGNALS ------------------------------------------------------
        days_after = max(1, (datetime.utcnow() - release_dt).days)
        rating_before = _avg([r.rating for r in before if r.rating is not None])
        rating_after = _avg([r.rating for r in after if r.rating is not None])
        rating_delta = (
            round(rating_after - rating_before, 3)
            if rating_before is not None and rating_after is not None
            else None
        )
        vel_before = round(len(before) / window_days, 2) if before else None
        vel_after = round(len(after) / days_after, 2) if after else None
        vel_delta = (
            round(vel_after - vel_before, 2)
            if vel_before is not None and vel_after is not None
            else None
        )
        neg_before = _neg_share(before)
        neg_after = _neg_share(after)
        neg_delta = (
            round(neg_after - neg_before, 1)
            if neg_before is not None and neg_after is not None
            else None
        )

        signals = {
            "rating_before": round(rating_before, 2) if rating_before is not None else None,
            "rating_after": round(rating_after, 2) if rating_after is not None else None,
            "rating_delta": rating_delta,
            "reviews_before": len(before),
            "reviews_after": len(after),
            "velocity_before_per_day": vel_before,
            "velocity_after_per_day": vel_after,
            "velocity_delta_per_day": vel_delta,
            "negative_share_before": round(neg_before, 1) if neg_before is not None else None,
            "negative_share_after": round(neg_after, 1) if neg_after is not None else None,
            "negative_share_delta_pp": neg_delta,
            "review_source": review_source,
            # metric (snapshot) signals — work without review text (iOS)
            "overall_rating": meta.avg_rating,
            "snapshot_baseline_date": prior.captured_at if prior else None,
            "metric_rating_delta": metric_rating_delta,
            "new_ratings_since_baseline": new_ratings_since,
        }

        # 5. VERDICT ------------------------------------------------------
        verdict = self._verdict(rating_delta, neg_delta, after, metric_rating_delta)
        if metric_rating_delta is None and not review_source:
            notes.append(
                "iOS/metrics-only: review text unavailable; rating trend will appear "
                "from the next run (snapshot baseline seeded today)."
            )

        # 6. LLM ISSUE CATEGORISATION ------------------------------------
        top_issues = self._categorise(after, deps, notes, lang)

        # 7. CAVEATS + SUMMARY -------------------------------------------
        if review_source == "sensortower":
            notes.append("Review/estimate data from Sensor Tower (paid source).")
        if len(after) < 5 and review_source:
            notes.append(f"Small post-release sample ({len(after)} reviews) — interpret with care.")

        summary = self._summarise(app_info, release_info, signals, verdict, top_issues, deps, notes, lang)

        return {
            "use_case": self.name,
            "lang": lang,
            "app": app_info,
            "release": release_info,
            "verdict": verdict,
            "signals": signals,
            "top_issues": top_issues,
            "notes": notes,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    def _resolve(self, app_query: str, store: str, deps, country=None, lang=None):
        if _looks_like_id(app_query, store):
            from connectors.base import AppRef

            return AppRef(app_id=app_query, name=app_query, store=store)
        search_conn = deps.connector_for(CAP_SEARCH, store)
        if search_conn is None:
            return None
        try:
            hits = search_conn.search_app(app_query, store, country=country, lang=lang)
        except ConnectorError:
            return None
        return hits[0] if hits else None

    def _verdict(self, rating_delta, neg_delta, after, metric_rating_delta=None) -> str:
        # Review-based signals first (richest — Android / scoped iOS token).
        if (rating_delta is not None and rating_delta <= REGRESSION_RATING_DROP) or (
            neg_delta is not None and neg_delta >= REGRESSION_NEG_SHARE_PP
        ):
            return "regression"
        if rating_delta is not None and rating_delta >= 0:
            return "healthy"
        # Metric-based fallback (iOS metrics-only, snapshot history available).
        # A flat trend is no signal, not a clean bill of health.
        if metric_rating_delta is not None:
            if metric_rating_delta <= METRIC_RATING_DROP:
                return "regression"
            if metric_rating_delta >= METRIC_RATING_RISE:
                return "healthy"
        return "inconclusive"

    def _categorise(self, after: list[Review], deps, notes: list[str], lang: str = "en") -> list[dict]:
        negatives = [r for r in after if r.rating is not None and r.rating <= 3 and r.content]
        if not negatives:
            return []
        sample = negatives[:20]
        joined = "\n".join(f"- ({r.rating}★) {r.content[:120]}" for r in sample)
        prompt = (
            "You are a product analyst. Categorise these post-release negative app "
            f"reviews into these categories: {', '.join(ISSUE_CATEGORIES)}.\n"
            "Return ONLY JSON: a list of objects "
            '{"category": str, "count": int, "examples": [up to 2 short quote strings]}, '
            "sorted by count descending, top 5 only. Keep example quotes verbatim in their "
            "original language.\n\n"
            f"Reviews:\n{joined}"
        )
        try:
            data = deps.llm.complete_json(prompt)
        except Exception as exc:  # noqa: BLE001 - LLM optional; degrade cleanly
            notes.append(f"Issue categorisation skipped (LLM unavailable: {exc}).")
            return []
        if isinstance(data, dict):
            data = data.get("issues") or data.get("categories") or []
        cleaned = []
        for it in data if isinstance(data, list) else []:
            if isinstance(it, dict) and it.get("category"):
                cleaned.append(
                    {
                        "category": it.get("category"),
                        "count": it.get("count", 0),
                        "examples": it.get("examples", [])[:2],
                    }
                )
        return cleaned[:5]

    def _summarise(self, app, release, signals, verdict, issues, deps, notes, lang="en") -> str:
        # Deterministic, localised one-line summary.
        rd = signals.get("rating_delta")
        mrd = signals.get("metric_rating_delta")
        vd = signals.get("velocity_delta_per_day")
        name, ver, date = app["name"], release["version"] or "", release["release_date"]
        if lang == "vi":
            vmap = {"healthy": "KHỎE", "regression": "TỤT LÙI", "inconclusive": "CHƯA KẾT LUẬN"}
            parts = [f"{name} {ver} (phát hành {date}): kết luận {vmap.get(verdict, verdict.upper())}."]
            if rd is not None:
                parts.append(f"Rating review {signals['rating_before']}→{signals['rating_after']} ({rd:+.2f}).")
            elif mrd is not None:
                parts.append(f"Rating tổng {mrd:+.3f} từ {signals.get('snapshot_baseline_date')} (xu hướng snapshot).")
            if vd is not None:
                parts.append(f"Tốc độ review {signals['velocity_before_per_day']}→{signals['velocity_after_per_day']}/ngày.")
            if issues:
                parts.append(f"Than phiền mới nhiều nhất: {issues[0]['category']} ({issues[0]['count']}).")
        else:
            parts = [f"{name} {ver} (released {date}): verdict {verdict.upper()}."]
            if rd is not None:
                parts.append(f"Review rating {signals['rating_before']}→{signals['rating_after']} ({rd:+.2f}).")
            elif mrd is not None:
                parts.append(f"Overall rating {mrd:+.3f} since {signals.get('snapshot_baseline_date')} (snapshot trend).")
            if vd is not None:
                parts.append(f"Review velocity {signals['velocity_before_per_day']}→{signals['velocity_after_per_day']}/day.")
            if issues:
                parts.append(f"Top new complaint: {issues[0]['category']} ({issues[0]['count']}).")
        return " ".join(parts)

    def _inconclusive(self, app, release, notes, source, lang="en") -> dict:
        summary = (
            f"{app['name']}: không đủ dữ liệu để kết luận sức khỏe bản cập nhật."
            if lang == "vi"
            else f"{app['name']}: insufficient data for a release-health verdict."
        )
        return {
            "use_case": self.name,
            "lang": lang,
            "app": app,
            "release": release,
            "verdict": "inconclusive",
            "signals": {"review_source": None},
            "top_issues": [],
            "notes": notes,
            "summary": summary,
        }
