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


def resolve_app(
    app_query: str, store: str, deps: "Deps", country: Optional[str] = None, lang: Optional[str] = None
) -> Optional[AppRef]:
    """Resolve a user query (name or store id) to an ``AppRef`` for ``store``.

    A store id is used as-is; otherwise the best search hit is returned (None if
    no search connector or no match). Shared by the store-facing use cases.
    """
    if looks_like_id(app_query, store):
        return AppRef(app_id=app_query, name=app_query, store=store)
    search_conn = deps.connector_for(CAP_SEARCH, store)
    if search_conn is None:
        return None
    try:
        hits = search_conn.search_app(app_query, store, country=country, lang=lang)
    except ConnectorError:
        return None
    return hits[0] if hits else None


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
