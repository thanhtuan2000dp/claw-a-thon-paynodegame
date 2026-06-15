"""iOS App Store charts connector — FREE, no auth.

Ranking only. Reads Apple's public Marketing-Tools RSS top-charts feed
(top-free / top-paid / top-grossing) for a country and reports where an app
sits in that chart.

Verified 2026-06-13: ``https://rss.marketingtools.apple.com/api/v2/{country}/
apps/{feed}/{limit}/apps.json`` returns the live chart as JSON (the older
``rss.applemarketingtools.com`` host 301-redirects here — httpx follows it).

LIMITATION: the feed is a *top-N list* (we request up to 200), so it can only
report a rank for apps that are currently in the top N — an app outside the
chart yields ``rank=None`` (not-in-chart), never a deep rank like #5000. It is
also a snapshot of *now*: the ``date`` argument is recorded on the RankPoint but
the data is always current (no historical charts on the free feed).

iOS only. Sensor Tower is still preferred for ranking (exact, any depth,
historical) — this is the free fallback.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import httpx

from core.cache import TTL_CHART, ttl_cache

from .base import CAP_CATEGORY, CAP_RANKING, AppDataConnector, AppRef, ConnectorError, RankPoint

BASE_URL = "https://rss.marketingtools.apple.com/api/v2"

# Map friendly category names to the feed slug Apple exposes. The public v2
# feed only serves top-free and top-paid (top-grossing is NOT available here —
# verified 2026-06-13, it 404s); grossing/revenue ranking needs a paid source.
_FEEDS = {
    "top-free": "top-free",
    "free": "top-free",
    "top-paid": "top-paid",
    "paid": "top-paid",
}
_DEFAULT_FEED = "top-free"


class IosChartsConnector(AppDataConnector):
    name = "ios_charts"
    stores = {"ios"}

    def __init__(self, country: str = "us", limit: int = 100, timeout: float = 15.0):
        self.country = country
        # Apple's v2 feed serves at most 100 entries; >100 returns HTTP 500
        # (verified 2026-06-13). So a not-in-top-100 app reports rank=None.
        self.limit = max(1, min(int(limit), 100))
        self.timeout = timeout

    def capabilities(self) -> set[str]:
        return {CAP_RANKING, CAP_CATEGORY}

    def category_apps(self, genre_id, store="ios", country=None, lang=None, limit=25) -> list[AppRef]:
        """Same-category competitors: the genre top-free chart, rank-ordered."""
        results = self._fetch_genre_chart(str(genre_id), country or self.country)
        refs: list[AppRef] = []
        for a in results[:limit]:
            if a.get("id"):
                refs.append(AppRef(app_id=str(a["id"]), name=a.get("name") or "", store="ios"))
        return refs

    def _feed_for(self, category: Optional[str]) -> str:
        if not category:
            return _DEFAULT_FEED
        return _FEEDS.get(category.strip().lower(), _DEFAULT_FEED)

    @ttl_cache(TTL_CHART)
    def _fetch_chart(self, feed: str, country: str) -> list[dict]:
        url = f"{BASE_URL}/{country.lower()}/apps/{feed}/{self.limit}/apps.json"
        try:
            resp = httpx.get(url, timeout=self.timeout, follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise ConnectorError(f"iOS charts {feed}/{country} failed: {exc}") from exc
        return data.get("feed", {}).get("results", []) or []

    @ttl_cache(TTL_CHART)
    def _fetch_genre_chart(self, genre_id: str, country: str) -> list[dict]:
        """Top-free chart WITHIN a genre via the old iTunes RSS (the marketingtools v2
        feed has no genre filter). Returns ordered apps — the app's position is its
        category rank, and the rest are its same-category competitors. Verified
        2026-06-14 (vn/6015 Finance). Up to 200 entries."""
        url = (f"https://itunes.apple.com/{country.lower()}/rss/topfreeapplications/"
               f"limit=200/genre={genre_id}/json")
        try:
            resp = httpx.get(url, timeout=self.timeout, follow_redirects=True)
            resp.raise_for_status()
            entries = resp.json().get("feed", {}).get("entry", []) or []
        except httpx.HTTPError as exc:
            raise ConnectorError(f"iOS genre chart {genre_id}/{country} failed: {exc}") from exc
        if isinstance(entries, dict):  # a single-entry feed comes back unwrapped
            entries = [entries]
        out = []
        for e in entries:
            out.append({
                "id": (e.get("id", {}).get("attributes", {}) or {}).get("im:id"),
                "name": (e.get("im:name", {}) or {}).get("label"),
                "genre": (e.get("category", {}).get("attributes", {}) or {}).get("label"),
            })
        return out

    def get_ranking(
        self, app_id: str, store: str, category: str, date: datetime,
        country: Optional[str] = None, lang: Optional[str] = None,
    ) -> RankPoint:
        cn = country or self.country  # charts are per-market — use the request's country
        cat = (category or "").strip()
        # A numeric category is a genre id -> report the in-CATEGORY rank (more useful
        # than the overall chart, where mid-size apps fall outside the top 100).
        if cat.isdigit():
            results = self._fetch_genre_chart(cat, cn)
            label = next((a["genre"] for a in results if a.get("genre")), cat)
            rank: Optional[int] = None
            for pos, app in enumerate(results, start=1):
                if str(app.get("id")) == str(app_id):
                    rank = pos
                    break
            return RankPoint(date=date, category=label, rank=rank)
        feed = self._feed_for(category)
        results = self._fetch_chart(feed, cn)
        rank = None
        for pos, app in enumerate(results, start=1):
            if str(app.get("id")) == str(app_id):
                rank = pos
                break
        # Report the feed slug as the category so callers see which chart it is.
        return RankPoint(date=date, category=feed, rank=rank)
