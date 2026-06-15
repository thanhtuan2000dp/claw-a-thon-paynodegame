"""Google Play connector — FREE, scraper-based (best-effort).

Provides search + metadata + reviews-with-timestamps via the
``google-play-scraper`` library. Android only. May be rate/IP-limited inside a
container; ``is_available`` guards the import so the agent still boots without
the library, and callers fall back per capabilities().
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

# Pulls the canonical package id out of a Play-store details URL embedded in the
# featured search result's raw data (used to recover the appId the scraper drops).
_DETAILS_ID_RE = re.compile(r"store/apps/details\?id=([A-Za-z0-9._]+)")

from core.cache import TTL_METADATA, TTL_REVIEWS, TTL_SEARCH, ttl_cache

from .base import (
    CAP_METADATA,
    CAP_REVIEWS,
    CAP_SEARCH,
    AppDataConnector,
    AppMetadata,
    AppRef,
    ConnectorError,
    Review,
)


def _epoch_to_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value))
    except (ValueError, TypeError, OSError):
        return None


class GooglePlayConnector(AppDataConnector):
    name = "googleplay"
    stores = {"android"}

    def __init__(self, country: str = "us", lang: str = "en", review_count: int = 100):
        self.country = country
        self.lang = lang
        self.review_count = review_count

    def capabilities(self) -> set[str]:
        return {CAP_SEARCH, CAP_METADATA, CAP_REVIEWS}

    def is_available(self) -> bool:
        try:
            import google_play_scraper  # noqa: F401

            return True
        except ImportError:
            return False

    @ttl_cache(TTL_SEARCH)
    def search_app(self, term: str, store: str = "android", country=None, lang=None) -> list[AppRef]:
        from google_play_scraper import search

        ln, cn = lang or self.lang, country or self.country
        try:
            hits = search(term, lang=ln, country=cn, n_hits=10)
        except Exception as exc:  # noqa: BLE001 - library raises plain Exceptions
            raise ConnectorError(f"Google Play search failed: {exc}") from exc

        # google-play-scraper drops the appId of the top "featured" result — which
        # is almost always the canonical app and the BEST match (e.g. "zalopay"
        # returns the real consumer app first with appId=None, so dropping it
        # leaves only the "ZaloPay Merchant" variant; "Spotify" → the 1B-install
        # app vs the TV app). Recover the real package id from the featured
        # result's own store URL in the raw page. Done once per search.
        refs: list[AppRef] = []
        seen: set[str] = set()
        recovered_featured = False
        for h in hits:
            app_id = h.get("appId")
            title = (h.get("title") or "").strip()
            if not app_id and title and not recovered_featured:
                recovered_featured = True
                app_id = self._recover_featured_app_id(term, ln, cn)
            if not app_id or app_id in seen:
                continue
            seen.add(app_id)
            refs.append(
                AppRef(app_id=app_id, name=title, store="android", publisher=h.get("developer"))
            )
        # Prefer an exact (case-insensitive) title match when present.
        refs.sort(key=lambda r: r.name.strip().lower() != term.strip().lower())
        return refs

    @staticmethod
    def _recover_featured_app_id(query: str, lang: str, country: str) -> Optional[str]:
        """Recover the appId the scraper drops for the top "featured" result.

        Re-fetches the search page with the library's own primitives, locates the
        featured block (same path the library parses), and pulls the canonical
        package id out of its embedded ``store/apps/details?id=...`` URL. Couples
        to google-play-scraper internals, so it is fully defensive: any failure
        returns None and the caller simply drops the un-recoverable hit.
        """
        try:
            from urllib.parse import quote

            from google_play_scraper.constants.regex import Regex
            from google_play_scraper.constants.request import Formats
            from google_play_scraper.utils.request import get

            dom = get(Formats.Searchresults.build(query=quote(query), lang=lang, country=country))
            dataset: dict = {}
            for match in Regex.SCRIPT.findall(dom):
                keys, values = Regex.KEY.findall(match), Regex.VALUE.findall(match)
                if keys and values:
                    dataset[keys[0]] = json.loads(values[0])
            featured = dataset["ds:4"][0][1][0][23][16]
            hit = _DETAILS_ID_RE.search(json.dumps(featured))
            return hit.group(1) if hit else None
        except Exception:  # noqa: BLE001 - best-effort; never break search on a layout change
            return None

    @ttl_cache(TTL_METADATA)
    def get_metadata(self, app_id: str, store: str = "android", country=None, lang=None) -> AppMetadata:
        from google_play_scraper import app as gp_app

        try:
            a = gp_app(app_id, lang=lang or self.lang, country=country or self.country)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"Google Play metadata failed: {exc}") from exc
        return AppMetadata(
            app_id=app_id,
            name=a.get("title", ""),
            store="android",
            version=a.get("version"),
            avg_rating=a.get("score"),
            rating_count=a.get("ratings"),
            current_version_release_date=_epoch_to_dt(a.get("updated")),
            first_release_date=None,
            release_notes=a.get("recentChanges"),
            publisher=a.get("developer"),
            category=a.get("genre"),
            price=(
                "Free"
                if a.get("free")
                else (f"{a.get('price')} {a.get('currency')}".strip() if a.get("price") is not None else None)
            ),
            icon_url=a.get("icon"),
            screenshot_urls=a.get("screenshots") or [],
            description=a.get("description"),
            raw={},
        )

    @ttl_cache(TTL_REVIEWS)
    def get_reviews(
        self, app_id: str, store: str, start_date: datetime, end_date: datetime, country=None, lang=None
    ) -> list[Review]:
        from google_play_scraper import Sort, reviews

        try:
            result, _ = reviews(
                app_id,
                lang=lang or self.lang,
                country=country or self.country,
                sort=Sort.NEWEST,
                count=self.review_count,
            )
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"Google Play reviews failed: {exc}") from exc

        out: list[Review] = []
        for r in result:
            at = r.get("at")  # library returns a datetime
            if at is not None:
                if start_date and at < start_date:
                    continue
                if end_date and at > end_date:
                    continue
            out.append(
                Review(
                    content=r.get("content", "") or "",
                    rating=r.get("score"),
                    title=None,
                    version=r.get("reviewCreatedVersion"),
                    date=at,
                    author=r.get("userName"),
                    source=self.name,
                )
            )
        return out
