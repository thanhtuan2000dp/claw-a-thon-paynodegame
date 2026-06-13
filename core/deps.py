"""Dependency container.

Builds the connector set, LLM, storage, and config once at startup and hands use
cases what they ask for. The key method is ``connector_for(capability, store)``:
use cases never name a source, they request a capability and get the best
available connector for it — so swapping sources is a config concern, not a code
change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from connectors.base import AppDataConnector
from core.conversation import ConversationStore, LocalConversationStore
from core.llm import LLM, make_llm
from core.registry import discover_connector_classes
from storage.snapshots import SnapshotStore

# Preferred connector order per capability (premium source first where it wins).
PREFERENCE: dict[str, list[str]] = {
    "reviews": ["sensortower", "googleplay"],
    "downloads": ["sensortower"],
    "ranking": ["sensortower", "ios_charts"],
    "metadata": ["itunes", "googleplay", "sensortower"],
    "search": ["itunes", "googleplay", "sensortower"],
}


@dataclass
class Deps:
    connectors: list[AppDataConnector]
    storage: SnapshotStore
    config: dict = field(default_factory=dict)
    conversation: ConversationStore = field(default_factory=LocalConversationStore)
    _llms: dict[str, LLM] = field(default_factory=dict)

    @property
    def llm(self) -> LLM:
        """The default model (env LLM_MODEL). Most call sites want this."""
        return self.llm_for()

    def llm_for(self, model: str | None = None) -> LLM:
        """An LLM bound to `model` (default: env LLM_MODEL), cached per model.

        All models share one endpoint + key, so this lets use cases mix models
        — e.g. a fast router model and a stronger narrative model — and call
        them concurrently. Lazy: connector-only paths and tests never build one.
        """
        key = model or os.environ.get("LLM_MODEL", "")
        if key not in self._llms:
            self._llms[key] = make_llm(model=model)
        return self._llms[key]

    def connectors_for(self, capability: str, store: str) -> list[AppDataConnector]:
        """All capable connectors, best-first. Callers can fall back through them
        when the preferred source errors (e.g. a token lacks reviews scope)."""
        order = PREFERENCE.get(capability, [])
        candidates = [c for c in self.connectors if c.supports(capability, store)]

        def rank(c: AppDataConnector) -> int:
            return order.index(c.name) if c.name in order else len(order)

        candidates.sort(key=rank)
        return candidates

    def connector_for(self, capability: str, store: str) -> AppDataConnector | None:
        candidates = self.connectors_for(capability, store)
        return candidates[0] if candidates else None

    def available_connectors(self) -> list[str]:
        return [c.name for c in self.connectors if c.is_available()]


def build_deps() -> Deps:
    country = os.environ.get("DEFAULT_COUNTRY", "us")
    connectors: list[AppDataConnector] = []
    for cls in discover_connector_classes():
        try:
            # Connectors accept country where relevant; SensorTower ignores it.
            try:
                connectors.append(cls(country=country))  # type: ignore[call-arg]
            except TypeError:
                connectors.append(cls())
        except Exception:  # noqa: BLE001 - a bad connector must not sink the agent
            continue

    storage = SnapshotStore(os.environ.get("SNAPSHOT_DIR", "data/snapshots"))
    conversation = LocalConversationStore(os.environ.get("CONVERSATION_DIR", "data/conversations"))
    config = {
        "default_store": os.environ.get("DEFAULT_STORE", "ios"),
        "default_country": country,
    }
    return Deps(connectors=connectors, storage=storage, conversation=conversation, config=config)
