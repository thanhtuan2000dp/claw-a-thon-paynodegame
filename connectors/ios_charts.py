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

from .base import CAP_RANKING, AppDataConnector, ConnectorError, RankPoint

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
        return {CAP_RANKING}

    def _feed_for(self, category: Optional[str]) -> str:
        if not category:
            return _DEFAULT_FEED
        return _FEEDS.get(category.strip().lower(), _DEFAULT_FEED)

    def _fetch_chart(self, feed: str, country: str) -> list[dict]:
        url = f"{BASE_URL}/{country.lower()}/apps/{feed}/{self.limit}/apps.json"
        try:
            resp = httpx.get(url, timeout=self.timeout, follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise ConnectorError(f"iOS charts {feed}/{country} failed: {exc}") from exc
        return data.get("feed", {}).get("results", []) or []

    def get_ranking(
        self, app_id: str, store: str, category: str, date: datetime
    ) -> RankPoint:
        feed = self._feed_for(category)
        results = self._fetch_chart(feed, self.country)
        rank: Optional[int] = None
        for pos, app in enumerate(results, start=1):
            if str(app.get("id")) == str(app_id):
                rank = pos
                break
        # Report the feed slug as the category so callers see which chart it is.
        return RankPoint(date=date, category=feed, rank=rank)
