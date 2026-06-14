"""App Store reviews connector — FREE, no auth. iOS only.

Verified 2026-06-14 against Zalo (id=579523206, market vn): App Store *review
text* IS available for free — contrary to the older "RSS feed is dead" note that
``itunes.py`` carried. Two undocumented endpoints, combined:

  • RSS customer-reviews feed
    ``itunes.apple.com/{country}/rss/customerreviews/id={id}/sortBy=mostRecent/page={1..10}/json``
    — correctly sorted newest→oldest, ~50 reviews/page, max 10 pages
    (~500 reviews ≈ the most recent ~1 month for a busy app). Two quirks:
      1. Some pages return HTTP 200 with an EMPTY body at random (Apple edge-cache
         eventual consistency). An empty page is NOT end-of-data — retry it before
         moving on (one retry is not enough; pages stay empty for several tries).
      2. In the ``/json`` variant EVERY entry is a real review; the app-metadata
         entry only exists in the XML feed. So we keep ``entry[0]`` (dropping it
         would lose the newest review). We still skip any entry without
         ``im:rating`` defensively.

  • Catalog API
    ``apps.apple.com/api/apps/v1/catalog/{country}/apps/{id}/reviews`` (empty
    Bearer header, no real token) — paginates deep via ``offset`` but IGNORES the
    ``sort`` param (order is relevance, dates interleaved 2021↔2025), so it can't
    stop early and must be filtered client-side. Used only to BACKFILL when the
    RSS window doesn't reach ``start_date``. ``amp-api.apps.apple.com`` needs a
    real Bearer token (401) — not used.

Both endpoints are undocumented; we throttle between requests and back off on
HTTP 429. This connector advertises only ``reviews`` — iTunes Lookup
(``itunes.py``) still owns search + metadata for iOS.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from .base import CAP_REVIEWS, AppDataConnector, ConnectorError, Review

_RSS_URL = (
    "https://itunes.apple.com/{country}/rss/customerreviews/"
    "id={app_id}/sortBy=mostRecent/page={page}/json"
)
_CATALOG_URL = "https://apps.apple.com/api/apps/v1/catalog/{country}/apps/{app_id}/reviews"
_CATALOG_HEADERS = {
    "Authorization": "Bearer",  # intentionally tokenless — the endpoint accepts it
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "x-apple-client-version": "2624.6.0-external",
}


# --- payload accessors (defensive: Apple's shapes drift; never KeyError) ---
def _label(node) -> Optional[str]:
    """RSS values are wrapped as {"label": ...}."""
    if isinstance(node, dict):
        v = node.get("label")
        return v if isinstance(v, str) else (str(v) if v is not None else None)
    return node if isinstance(node, str) else None


def _author_name(entry: dict) -> Optional[str]:
    author = entry.get("author")
    if isinstance(author, dict):
        return _label(author.get("name"))
    return None


def _to_int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _to_naive_utc(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 stamp (RSS uses ``-07:00``, Catalog uses ``Z``) into a
    naive-UTC datetime so it compares cleanly with the use case's naive bounds."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class AppStoreReviewsConnector(AppDataConnector):
    name = "appstore_reviews"
    stores = {"ios"}

    def __init__(
        self,
        country: str = "us",
        lang: Optional[str] = None,
        timeout: float = 15.0,
        max_rss_pages: int = 10,
        empty_retries: int = 6,
        deep_backfill: bool = True,
        max_catalog_pages: int = 25,
    ):
        self.country = country
        self.lang = lang
        self.timeout = timeout
        self.max_rss_pages = min(max_rss_pages, 10)  # RSS hard-caps at 10 (page>=11 -> HTTP 400)
        self.empty_retries = empty_retries
        self.deep_backfill = deep_backfill
        self.max_catalog_pages = max_catalog_pages

    def capabilities(self) -> set[str]:
        return {CAP_REVIEWS}

    def get_reviews(
        self,
        app_id: str,
        store: str,
        start_date: datetime,
        end_date: datetime,
        country: Optional[str] = None,
        lang: Optional[str] = None,
    ) -> list[Review]:
        cn = country or self.country
        ln = lang or self.lang
        out: dict[str, Review] = {}  # id -> Review (dedup; RSS & Catalog share the numeric id space)

        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            # RSS first: cheap, pre-sorted, covers the recent window in a few pages.
            reached_start = self._collect_rss(client, app_id, cn, start_date, end_date, out)
            # Only quarry the deep (unsorted, 429-prone) Catalog when RSS ran out of
            # pages before reaching the window's start — i.e. a long window on a
            # high-volume app. Short windows never trigger this.
            if self.deep_backfill and not reached_start:
                self._collect_catalog(client, app_id, cn, ln, start_date, end_date, out)

        return sorted(out.values(), key=lambda r: r.date or datetime.min, reverse=True)

    # ------------------------------------------------------------------ RSS
    def _collect_rss(self, client, app_id, country, start_date, end_date, out) -> bool:
        """Populate ``out`` from the RSS feed. Returns True if we reached the
        window's start (an older-than-start review seen, or HTTP 400 = no more
        pages); False if RSS pages ran out while still inside the window."""
        got_any = False
        for page in range(1, self.max_rss_pages + 1):
            try:
                entries = self._fetch_rss_page(client, app_id, country, page)
            except ConnectorError:
                if got_any:
                    return False  # partial data already gathered; let caller backfill
                raise
            if entries is None:  # HTTP 400 -> past the last valid page -> bottom reached
                return True
            got_any = got_any or bool(entries)
            if not entries:  # stubbornly empty after retries -> skip (leaves a gap), keep going
                continue
            for e in entries:
                if "im:rating" not in e:  # /json: all entries are reviews; guard vs XML metadata entry
                    continue
                d = _to_naive_utc(_label(e.get("updated")))
                if d is None:
                    continue
                if start_date and d < start_date:  # feed is sorted desc -> everything below is out of window
                    return True
                if end_date and d > end_date:  # future/edited stamp past the window -> skip, keep scanning
                    continue
                rid = _label(e.get("id")) or f"rss:{page}:{len(out)}"
                out.setdefault(
                    rid,
                    Review(
                        content=_label(e.get("content")) or "",
                        rating=_to_int(_label(e.get("im:rating"))),
                        title=_label(e.get("title")),
                        version=_label(e.get("im:version")),
                        date=d,
                        author=_author_name(e),
                        source=self.name,
                    ),
                )
            time.sleep(0.5)  # gentle pacing between pages
        if not got_any:
            raise ConnectorError("App Store RSS returned no reviews (all pages empty/unreachable)")
        return False

    def _fetch_rss_page(self, client, app_id, country, page) -> Optional[list]:
        """One RSS page, retrying the random empty-body responses. Returns the
        entry list (possibly empty if it stays empty), or None on HTTP 400
        (no such page). Raises ConnectorError on network failure."""
        url = _RSS_URL.format(country=country, app_id=app_id, page=page)
        for _ in range(self.empty_retries):
            try:
                resp = client.get(url, headers={"User-Agent": "review-agent/1.0"})
            except httpx.HTTPError as exc:
                raise ConnectorError(f"App Store RSS request failed: {exc}") from exc
            if resp.status_code == 400:
                return None
            if resp.status_code == 429:
                time.sleep(3)
                continue
            if resp.status_code != 200:
                raise ConnectorError(f"App Store RSS HTTP {resp.status_code}")
            try:
                entries = resp.json().get("feed", {}).get("entry", [])
            except ValueError:
                entries = []
            if isinstance(entries, dict):  # a single-entry page comes back unwrapped
                entries = [entries]
            if entries:
                return entries
            time.sleep(1.0)  # empty body -> wait then retry (NOT end-of-data)
        return []  # exhausted retries; treat as a skippable gap

    # -------------------------------------------------------------- Catalog
    def _collect_catalog(self, client, app_id, country, lang, start_date, end_date, out) -> None:
        """Deep backfill from the Catalog API. It ignores ``sort`` (dates are
        interleaved), so we cannot stop early — we page through up to
        ``max_catalog_pages`` and filter client-side. Best-effort: any hard
        failure just stops the backfill with whatever we have."""
        url = _CATALOG_URL.format(country=country, app_id=app_id)
        params = {"l": lang or "en-us", "platform": "web", "limit": 20, "offset": 0}
        misses = 0
        pages = 0
        while pages < self.max_catalog_pages:
            try:
                resp = client.get(url, params=params, headers=_CATALOG_HEADERS)
            except httpx.HTTPError:
                return  # network blip -> keep RSS results
            if resp.status_code == 429:
                misses += 1
                if misses > 8:
                    return  # give up after sustained throttling
                time.sleep(5)  # back off WITHOUT advancing offset
                continue
            if resp.status_code != 200:
                return
            misses = 0
            try:
                data = resp.json()
            except ValueError:
                return
            rows = data.get("data", [])
            if not rows:
                return
            for it in rows:
                attrs = it.get("attributes", {}) if isinstance(it, dict) else {}
                d = _to_naive_utc(attrs.get("date"))
                if d is None:
                    continue
                if (start_date and d < start_date) or (end_date and d > end_date):
                    continue
                rid = str(it.get("id") or f"cat:{params['offset']}:{len(out)}")
                out.setdefault(
                    rid,
                    Review(
                        content=attrs.get("review", "") or "",
                        rating=_to_int(attrs.get("rating")),
                        title=attrs.get("title"),
                        version=None,  # Catalog payload has no per-review version
                        date=d,
                        author=attrs.get("userName"),
                        source=self.name,
                    ),
                )
            if not data.get("next"):
                return
            params["offset"] += 20
            pages += 1
            time.sleep(0.4)  # pace to avoid 429
