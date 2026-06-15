"""iTunes / App Store connector — FREE, no auth. iOS only.

Verified 2026-06-13: Search + Lookup return rich metadata (avg rating, rating
count, current version + release date, release notes). This connector serves
**search + metadata only**.

iOS *review text* is provided by a separate connector (``appstore_reviews``).
NB: the customer-reviews RSS feed is NOT dead — a single call often returns an
empty body (which earlier read as "dead"), but with empty-page retries it works
and is correctly sorted newest→oldest. See ``appstore_reviews.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import httpx

from core.cache import TTL_METADATA, TTL_SEARCH, ttl_cache

from .base import (
    CAP_METADATA,
    CAP_SEARCH,
    AppDataConnector,
    AppMetadata,
    AppRef,
    ConnectorError,
)

SEARCH_URL = "https://itunes.apple.com/search"
LOOKUP_URL = "https://itunes.apple.com/lookup"


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class ItunesConnector(AppDataConnector):
    name = "itunes"
    stores = {"ios"}

    def __init__(self, country: str = "us", timeout: float = 15.0):
        self.country = country
        self.timeout = timeout

    def capabilities(self) -> set[str]:
        return {CAP_SEARCH, CAP_METADATA}

    def _get(self, url: str, params: dict) -> dict:
        try:
            resp = httpx.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise ConnectorError(f"iTunes request failed: {exc}") from exc

    @ttl_cache(TTL_SEARCH)
    def search_app(self, term: str, store: str = "ios", country=None, lang=None) -> list[AppRef]:
        data = self._get(
            SEARCH_URL,
            {"term": term, "entity": "software", "limit": 10, "country": country or self.country},
        )
        refs: list[AppRef] = []
        for item in data.get("results", []):
            track_id = item.get("trackId")
            if track_id is None:
                continue
            refs.append(
                AppRef(
                    app_id=str(track_id),
                    name=item.get("trackName", ""),
                    store="ios",
                    publisher=item.get("sellerName"),
                )
            )
        return refs

    @ttl_cache(TTL_METADATA)
    def get_metadata(self, app_id: str, store: str = "ios", country=None, lang=None) -> AppMetadata:
        data = self._get(LOOKUP_URL, {"id": app_id, "country": country or self.country})
        results = data.get("results", [])
        if not results:
            raise ConnectorError(f"iTunes: app id {app_id} not found in {self.country}")
        a = results[0]
        return AppMetadata(
            app_id=str(a.get("trackId", app_id)),
            name=a.get("trackName", ""),
            store="ios",
            version=a.get("version"),
            avg_rating=a.get("averageUserRating"),
            rating_count=a.get("userRatingCount"),
            current_version_release_date=_parse_dt(a.get("currentVersionReleaseDate")),
            first_release_date=_parse_dt(a.get("releaseDate")),
            release_notes=a.get("releaseNotes"),
            publisher=a.get("sellerName"),
            category=a.get("primaryGenreName"),
            genre_id=(str(a["primaryGenreId"]) if a.get("primaryGenreId") is not None
                      else (a.get("genreIds") or [None])[0]),
            price=a.get("formattedPrice")
            or (str(a.get("price")) if a.get("price") is not None else None),
            icon_url=a.get("artworkUrl512") or a.get("artworkUrl100") or a.get("artworkUrl60"),
            screenshot_urls=a.get("screenshotUrls") or [],
            description=a.get("description"),
            raw=a,
        )
