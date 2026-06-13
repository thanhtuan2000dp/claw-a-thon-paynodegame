"""Sensor Tower connector (formerly data.ai / App Annie) — PREMIUM, keyed.

Activates only when ``SENSORTOWER_AUTH_TOKEN`` is set. Provides the data the free
sources cannot: reviews with dates+ratings, download/revenue estimates, and
category rankings — across iOS, Android, and unified.

Base URL: https://api.sensortower.com  ·  Auth: ``auth_token`` query param.

NOTE: exact response field names vary by API version and subscription tier.
Parsing here is defensive (missing fields -> None); if a field comes back under a
different key for your plan, adjust the small ``_parse_*`` helpers below. Any
failure raises ConnectorError so use cases degrade to free sources rather than
crash. Verify endpoint availability against your plan at app.sensortower.com.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import httpx

from .base import (
    CAP_DOWNLOADS,
    CAP_METADATA,
    CAP_RANKING,
    CAP_REVIEWS,
    CAP_SEARCH,
    AppDataConnector,
    AppMetadata,
    AppRef,
    ConnectorError,
    DownloadPoint,
    RankPoint,
    Review,
)

BASE_URL = "https://api.sensortower.com"
_OS = {"ios": "ios", "android": "android", "unified": "unified"}


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class SensorTowerConnector(AppDataConnector):
    name = "sensortower"
    stores = {"ios", "android", "unified"}

    def __init__(self, auth_token: Optional[str] = None, timeout: float = 20.0):
        self.auth_token = auth_token or os.environ.get("SENSORTOWER_AUTH_TOKEN", "")
        self.timeout = timeout

    def capabilities(self) -> set[str]:
        return {CAP_SEARCH, CAP_METADATA, CAP_REVIEWS, CAP_DOWNLOADS, CAP_RANKING}

    def is_available(self) -> bool:
        return bool(self.auth_token)

    def _os(self, store: str) -> str:
        return _OS.get(store, "ios")

    def _get(self, path: str, params: dict) -> dict | list:
        params = {**params, "auth_token": self.auth_token}
        try:
            resp = httpx.get(f"{BASE_URL}{path}", params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            # IMPORTANT: never include the URL/message verbatim — it carries the
            # auth_token. Report status + path only (this surfaces in API responses).
            raise ConnectorError(
                f"Sensor Tower {path} -> HTTP {exc.response.status_code}"
            ) from None
        except httpx.HTTPError as exc:
            msg = str(exc).replace(self.auth_token, "<redacted>") if self.auth_token else str(exc)
            raise ConnectorError(f"Sensor Tower {path} failed: {msg}") from None

    # --- search ---
    def search_app(self, term: str, store: str = "ios", country=None, lang=None) -> list[AppRef]:
        data = self._get(
            f"/v1/{self._os(store)}/search_entities",
            {"entity_type": "app", "term": term, "limit": 10},
        )
        items = data if isinstance(data, list) else data.get("apps", data.get("results", []))
        refs: list[AppRef] = []
        for it in items:
            app_id = it.get("app_id") or it.get("id") or it.get("appId")
            if app_id is None:
                continue
            refs.append(
                AppRef(
                    app_id=str(app_id),
                    name=it.get("name") or it.get("humanized_name") or "",
                    store=store,
                    publisher=it.get("publisher_name") or it.get("developer"),
                )
            )
        return refs

    # --- metadata ---
    def get_metadata(self, app_id: str, store: str = "ios", country=None, lang=None) -> AppMetadata:
        data = self._get(
            f"/v1/{self._os(store)}/apps",
            {"app_ids": app_id, "country": (country or "US").upper()},
        )
        apps = data.get("apps", data) if isinstance(data, dict) else data
        if not apps:
            raise ConnectorError(f"Sensor Tower: app {app_id} not found")
        a = apps[0] if isinstance(apps, list) else apps
        return AppMetadata(
            app_id=str(a.get("app_id", app_id)),
            name=a.get("name") or a.get("humanized_name") or "",
            store=store,
            version=a.get("version"),
            avg_rating=a.get("rating") or a.get("current_version_rating"),
            rating_count=a.get("rating_count"),
            current_version_release_date=_parse_dt(a.get("current_version_release_date") or a.get("updated_date")),
            first_release_date=_parse_dt(a.get("release_date")),
            release_notes=a.get("release_notes"),
            publisher=a.get("publisher_name"),
            raw=a if isinstance(a, dict) else {},
        )

    # --- reviews ---
    def get_reviews(
        self, app_id: str, store: str, start_date: datetime, end_date: datetime, country=None, lang=None
    ) -> list[Review]:
        data = self._get(
            f"/v1/{self._os(store)}/review/get_reviews",
            {
                "app_id": app_id,
                "country": (country or "US").upper(),
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "limit": 200,
            },
        )
        items = data.get("feedback", data.get("reviews", [])) if isinstance(data, dict) else data
        out: list[Review] = []
        for r in items or []:
            out.append(
                Review(
                    content=r.get("review") or r.get("content") or r.get("body") or "",
                    rating=r.get("rating") or r.get("score"),
                    title=r.get("title"),
                    version=r.get("version"),
                    date=_parse_dt(r.get("date") or r.get("created_at")),
                    author=r.get("author") or r.get("username"),
                    source=self.name,
                )
            )
        return out

    # --- downloads / revenue ---
    def get_downloads(
        self, app_id: str, store: str, start_date: datetime, end_date: datetime
    ) -> list[DownloadPoint]:
        data = self._get(
            f"/v1/{self._os(store)}/sales_report_estimates",
            {
                "app_ids": app_id,
                "countries": "WW",
                "date_granularity": "daily",
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
            },
        )
        items = data if isinstance(data, list) else data.get("data", [])
        out: list[DownloadPoint] = []
        for p in items or []:
            revenue = p.get("revenue") or p.get("r")
            # Sensor Tower revenue estimates are typically in cents.
            revenue_usd = (revenue / 100.0) if isinstance(revenue, (int, float)) else None
            out.append(
                DownloadPoint(
                    date=_parse_dt(p.get("date") or p.get("d")) or start_date,
                    units=p.get("units") or p.get("u"),
                    revenue_usd=revenue_usd,
                )
            )
        return out

    # --- ranking ---
    def get_ranking(
        self, app_id: str, store: str, category: str, date: datetime
    ) -> RankPoint:
        data = self._get(
            f"/v1/{self._os(store)}/ranking",
            {
                "app_id": app_id,
                "category": category,
                "date": date.strftime("%Y-%m-%d"),
            },
        )
        rank = None
        if isinstance(data, dict):
            rank = data.get("rank") or data.get("ranking")
        return RankPoint(date=date, category=category, rank=rank)
