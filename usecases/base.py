"""Use-case contract.

Every capability the agent exposes (UC1 release health, the hypothesis checker,
and later UC2-UC4) is a ``UseCase``. To add one: create a module in this package
with a UseCase subclass — the registry discovers it automatically, the router can
dispatch to it by ``name``, and nothing else needs to change.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from connectors.base import CAP_SEARCH, AppRef, ConnectorError

if TYPE_CHECKING:
    from core.deps import Deps


def looks_like_id(app: str, store: str) -> bool:
    """True if ``app`` is already a store id (iOS numeric trackId / Android package),
    so we can skip search and use it directly."""
    if store == "ios":
        return app.isdigit()
    return bool(re.fullmatch(r"[a-zA-Z][\w.]+\.[\w.]+", app))


# Stores to try when the requested country has no good match — apps are commonly
# present in the US store even when absent from a smaller local store.
_FALLBACK_COUNTRIES = ["us"]
# Below this title-similarity, the local store has no real match → try a fallback.
_GOOD_MATCH = 0.75


def _norm(text: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _match_score(query: str, name: str) -> float:
    """Title-similarity in [0, 1] for ranking search hits against the query:
    exact > prefix > fraction of query words present. Keeps the resolver from
    picking a loosely-related app (e.g. 'Dead Trigger' for 'dead target')."""
    q, n = _norm(query), _norm(name)
    if not q or not n:
        return 0.0
    if n == q:
        return 1.0
    if n.startswith(q + " "):
        return 0.9
    qt = q.split()
    covered = sum(1 for t in qt if t in set(n.split())) / len(qt)
    return 0.6 * covered


def resolve_app(
    app_query: str, store: str, deps: "Deps", country: Optional[str] = None, lang: Optional[str] = None
) -> Optional[AppRef]:
    """Resolve a user query (name or store id) to an ``AppRef`` for ``store``.

    A store id is used as-is. Otherwise search hits are **ranked by title
    similarity** (not blindly taking the first hit), and if the requested country
    has no good match the search **falls back to other countries** (e.g. US). The
    returned ref carries ``country`` = the store country it was found in, so callers
    fetch metadata/reviews from the right store. Returns None if nothing resolves.
    """
    if looks_like_id(app_query, store):
        return AppRef(app_id=app_query, name=app_query, store=store, country=country)
    search_conn = deps.connector_for(CAP_SEARCH, store)
    if search_conn is None:
        return None

    countries: list[Optional[str]] = []
    for c in [country, *_FALLBACK_COUNTRIES]:
        if c not in countries:
            countries.append(c)

    best_overall: Optional[AppRef] = None
    best_score = -1.0
    for c in countries:
        try:
            hits = search_conn.search_app(app_query, store, country=c, lang=lang)
        except ConnectorError:
            continue
        if not hits:
            continue
        best = max(hits, key=lambda h: _match_score(app_query, h.name))
        score = _match_score(app_query, best.name)
        best.country = c
        if score >= _GOOD_MATCH:
            return best  # strong match in a preferred country — stop, no extra calls
        if score > best_score:
            best_overall, best_score = best, score
    return best_overall


def snapshot_app(
    app_query: str, store: str, deps: "Deps", country: Optional[str] = None, lang: Optional[str] = None
) -> Optional[dict]:
    """Resolve an app, fetch current metadata + category rank, append a daily snapshot,
    and return ``{ref, meta, rank, rank_chart, history}``. Returns None if it can't
    resolve or fetch metadata. Shared by the snapshot-trend use cases (UC4/UC9) — does
    NOT touch uc1's own copy. Ranking failures degrade to rank=None (silent)."""
    from datetime import datetime

    from connectors.base import CAP_METADATA, CAP_RANKING
    from storage.snapshots import Snapshot

    ref = resolve_app(app_query, store, deps, country, lang)
    if ref is None or not ref.app_id:
        return None
    country = ref.country or country  # use the store the app was actually found in
    meta_conn = deps.connector_for(CAP_METADATA, store)
    if meta_conn is None:
        return None
    try:
        meta = meta_conn.get_metadata(ref.app_id, store, country=country, lang=lang)
    except ConnectorError:
        return None

    rank, rank_chart = None, None
    for rc in deps.connectors_for(CAP_RANKING, store):
        try:
            rp = rc.get_ranking(meta.app_id, store, meta.genre_id or "top-free",
                                datetime.utcnow(), country=country, lang=lang)
            rank, rank_chart = rp.rank, rp.category
            break
        except ConnectorError:
            continue

    rel = meta.current_version_release_date
    deps.storage.save(Snapshot(
        captured_at=datetime.utcnow().date().isoformat(),
        app_id=meta.app_id, store=store, version=meta.version,
        avg_rating=meta.avg_rating, rating_count=meta.rating_count,
        current_version_release_date=rel.isoformat() if rel else None, rank=rank,
        release_notes=(meta.release_notes or "").strip()[:1000] or None,
    ))
    return {"ref": ref, "meta": meta, "rank": rank, "rank_chart": rank_chart,
            "history": deps.storage.history(meta.app_id, store)}


class UseCase(ABC):
    #: stable identifier used as the ``action`` in requests
    name: str = "base"
    #: one-line human description (shown to the LLM router and in help)
    description: str = ""
    #: lightweight {param: description} map for prompting / docs
    input_schema: dict[str, str] = {}

    @abstractmethod
    def run(self, params: dict, deps: "Deps", context=None) -> dict:
        """Execute the use case and return a JSON-serialisable result dict.

        ``context`` carries request metadata (e.g. session_id) for multi-turn use
        cases. Single-shot use cases accept and ignore it.
        """
