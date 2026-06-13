"""Conversation store for multi-turn use cases (the Hypothesis Checker).

Abstracts WHERE turn-by-turn conversation state lives so the multi-turn logic is
testable locally and the backend is swappable. ``LocalConversationStore`` (JSON
per session) is used for local dev/tests; an AgentBase Memory-backed store is
swapped in at deploy time without touching the use case.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod


class ConversationStore(ABC):
    @abstractmethod
    def append(self, session_id: str, role: str, content: str) -> None:
        """Append one turn ({role: 'user'|'assistant', content})."""

    @abstractmethod
    def history(self, session_id: str) -> list[dict]:
        """Return ordered turns: [{'role':..., 'content':...}, ...]."""

    @abstractmethod
    def clear(self, session_id: str) -> None:
        """Drop a session (called when a hypothesis run completes)."""


class LocalConversationStore(ConversationStore):
    def __init__(self, base_dir: str = "data/conversations"):
        self.base_dir = base_dir

    def _path(self, session_id: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)[:120]
        return os.path.join(self.base_dir, f"{safe or 'default'}.json")

    def append(self, session_id: str, role: str, content: str) -> None:
        os.makedirs(self.base_dir, exist_ok=True)
        turns = self.history(session_id)
        turns.append({"role": role, "content": content})
        with open(self._path(session_id), "w", encoding="utf-8") as fh:
            json.dump(turns, fh, ensure_ascii=False)

    def history(self, session_id: str) -> list[dict]:
        path = self._path(session_id)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def clear(self, session_id: str) -> None:
        path = self._path(session_id)
        if os.path.exists(path):
            os.remove(path)
