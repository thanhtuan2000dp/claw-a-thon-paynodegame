"""Google Play connector — FREE, scraper-based (best-effort).

Provides search + metadata + reviews-with-timestamps via the
``google-play-scraper`` library. Android only. May be rate/IP-limited inside a
container; ``is_available`` guards the import so the agent still boots without
the library, and callers fall back per capabilities().
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

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

    def search_app(self, term: str, store: str = "android", country=None, lang=None) -> list[AppRef]:
        from google_play_scraper import search

        try:
            hits = search(term, lang=lang or self.lang, country=country or self.country, n_hits=10)
        except Exception as exc:  # noqa: BLE001 - library raises plain Exceptions
            raise ConnectorError(f"Google Play search failed: {exc}") from exc
        refs = [
            AppRef(
                app_id=h["appId"],
                name=h.get("title", ""),
                store="android",
                publisher=h.get("developer"),
            )
            for h in hits
            if h.get("appId")  # search sometimes returns a null-id placeholder first
        ]
        # Prefer an exact (case-insensitive) title match when present.
        refs.sort(key=lambda r: r.name.strip().lower() != term.strip().lower())
        return refs

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
            raw={},
        )

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
