"""Data-source connector contract.

Every data source (iTunes, Google Play, Sensor Tower, ...) implements
``AppDataConnector``. Use cases never talk to a specific source — they ask the
dependency container for "a connector that can do X for store Y", so adding or
removing a source never touches use-case code.

This module is pure Python (no greennode-agentbase / no network framework) so it
can be unit-tested standalone.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# A store is one of: "ios", "android". Sensor Tower also understands "unified".
Store = str

# Capability tokens a connector may advertise via capabilities().
CAP_SEARCH = "search"
CAP_METADATA = "metadata"
CAP_REVIEWS = "reviews"
CAP_DOWNLOADS = "downloads"
CAP_RANKING = "ranking"
CAP_CATEGORY = "category"  # list the apps in a store category/genre (competitor discovery)


class NotSupported(Exception):
    """Raised when a connector is asked for a capability it does not provide."""


class ConnectorError(Exception):
    """Raised when an available connector fails at runtime (network, auth, ...)."""


@dataclass
class AppRef:
    """A resolved app handle returned by search."""

    app_id: str
    name: str
    store: Store
    publisher: Optional[str] = None


@dataclass
class AppMetadata:
    """Aggregate app facts. ``raw`` keeps the untouched source payload."""

    app_id: str
    name: str
    store: Store
    version: Optional[str] = None
    avg_rating: Optional[float] = None
    rating_count: Optional[int] = None
    current_version_release_date: Optional[datetime] = None
    first_release_date: Optional[datetime] = None
    release_notes: Optional[str] = None
    publisher: Optional[str] = None
    # Store-listing fields (sheet UC1 — populated best-effort from the raw payload).
    category: Optional[str] = None
    genre_id: Optional[str] = None  # store genre id (iOS: primaryGenreId) for category rank
    price: Optional[str] = None
    icon_url: Optional[str] = None
    screenshot_urls: list[str] = field(default_factory=list)
    description: Optional[str] = None
    raw: dict = field(default_factory=dict)


@dataclass
class Review:
    content: str
    rating: Optional[int] = None
    title: Optional[str] = None
    version: Optional[str] = None
    date: Optional[datetime] = None
    author: Optional[str] = None
    source: Optional[str] = None  # connector name that produced it


@dataclass
class DownloadPoint:
    date: datetime
    units: Optional[int] = None
    revenue_usd: Optional[float] = None


@dataclass
class RankPoint:
    date: datetime
    category: str
    rank: Optional[int] = None


class AppDataConnector(ABC):
    """Abstract data source.

    Implementations set ``name`` and ``stores`` and override the methods matching
    the capabilities they advertise. Unsupported methods raise ``NotSupported``
    (the default below), so callers can rely on capabilities() to gate calls.
    """

    name: str = "base"
    stores: set[Store] = set()

    @abstractmethod
    def capabilities(self) -> set[str]:
        """Subset of CAP_* this connector can serve."""

    def is_available(self) -> bool:
        """Whether the connector is usable right now (e.g. token present, lib importable)."""
        return True

    def supports(self, capability: str, store: Store) -> bool:
        return (
            self.is_available()
            and capability in self.capabilities()
            and (not self.stores or store in self.stores)
        )

    # --- capability methods (override the ones you advertise) ---
    # country/lang override the connector's defaults per request (market-aware:
    # a Vietnamese query analyses the VN store, English the US store).

    def search_app(
        self, term: str, store: Store, country: Optional[str] = None, lang: Optional[str] = None
    ) -> list[AppRef]:
        raise NotSupported(f"{self.name} does not support search")

    def get_metadata(
        self, app_id: str, store: Store, country: Optional[str] = None, lang: Optional[str] = None
    ) -> AppMetadata:
        raise NotSupported(f"{self.name} does not support metadata")

    def get_reviews(
        self,
        app_id: str,
        store: Store,
        start_date: datetime,
        end_date: datetime,
        country: Optional[str] = None,
        lang: Optional[str] = None,
    ) -> list[Review]:
        raise NotSupported(f"{self.name} does not support reviews")

    def get_downloads(
        self, app_id: str, store: Store, start_date: datetime, end_date: datetime
    ) -> list[DownloadPoint]:
        raise NotSupported(f"{self.name} does not support downloads")

    def get_ranking(
        self, app_id: str, store: Store, category: str, date: datetime,
        country: Optional[str] = None, lang: Optional[str] = None,
    ) -> RankPoint:
        raise NotSupported(f"{self.name} does not support ranking")

    def category_apps(
        self, genre_id: str, store: Store, country: Optional[str] = None,
        lang: Optional[str] = None, limit: int = 25,
    ) -> list[AppRef]:
        """Apps currently in a store category/genre, rank-ordered — for discovering
        an app's same-category competitors."""
        raise NotSupported(f"{self.name} does not support category listing")
