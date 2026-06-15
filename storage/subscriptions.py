"""Subscription store — per-user UC9 alert subscriptions.

A subscription says "send anomaly alerts for app X to Telegram chat C on schedule
S". The destination ``chat_id`` is the identity (self-serve): the bot token stays
a server secret and is never stored here. ``SubscriptionStore`` keeps all records
in one JSON file under ``base_dir``.

Durability mirrors snapshots: durable iff ``SUBSCRIPTION_DIR`` points at a
persistent volume (see CLAUDE.md → "Durable storage"). ``SubscriptionStoreBase``
is the seam for a managed backend.
"""

from __future__ import annotations

import json
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Subscription:
    chat_id: str                       # Telegram chat to deliver to (the identity)
    app: str                           # app name or store id to watch
    store: str = "ios"                 # ios | android | both
    lang: Optional[str] = None         # vi | en (output language); None = auto
    country: Optional[str] = None      # two-letter store country; None = from lang
    freq: str = "daily"                # daily | weekly
    hour: int = 9                      # local hour 0-23 (in ALERT_TZ)
    weekday: Optional[int] = None      # 0=Mon..6=Sun, required for weekly
    label: Optional[str] = None        # optional human label
    active: bool = True
    created_at: Optional[str] = None   # ISO timestamp
    last_sent: Optional[str] = None    # ISO date of the last delivery (dedup guard)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


class SubscriptionStoreBase(ABC):
    """Backend seam for alert subscriptions."""

    @abstractmethod
    def add(self, sub: Subscription) -> Subscription:
        """Persist a new subscription, returning the stored record (with id)."""

    @abstractmethod
    def list(self, chat_id: Optional[str] = None) -> list[Subscription]:
        """All subscriptions, or just those for ``chat_id`` when given."""

    @abstractmethod
    def get(self, sub_id: str) -> Optional[Subscription]:
        """One subscription by id, or None."""

    @abstractmethod
    def delete(self, sub_id: str, chat_id: Optional[str] = None) -> bool:
        """Remove a subscription. When ``chat_id`` is given it must match (so a
        caller can only delete its own). Returns True if something was removed."""

    @abstractmethod
    def all_active(self) -> list[Subscription]:
        """Every active subscription (for the scheduler)."""

    @abstractmethod
    def mark_sent(self, sub_id: str, date_iso: str) -> None:
        """Record the date a subscription was last delivered (dedup guard)."""

    @abstractmethod
    def count(self, chat_id: Optional[str] = None) -> int:
        """Total subscriptions, or just those for ``chat_id``."""


class SubscriptionStore(SubscriptionStoreBase):
    def __init__(self, base_dir: str = "data/subscriptions"):
        self.base_dir = base_dir

    def _path(self) -> str:
        return os.path.join(self.base_dir, "subscriptions.json")

    def _load(self) -> list[dict]:
        path = self._path()
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def _save(self, rows: list[dict]) -> None:
        os.makedirs(self.base_dir, exist_ok=True)
        with open(self._path(), "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)

    def add(self, sub: Subscription) -> Subscription:
        rows = self._load()
        rows.append(asdict(sub))
        self._save(rows)
        return sub

    def list(self, chat_id: Optional[str] = None) -> list[Subscription]:
        rows = self._load()
        subs = [Subscription(**r) for r in rows]
        return [s for s in subs if chat_id is None or s.chat_id == chat_id]

    def get(self, sub_id: str) -> Optional[Subscription]:
        for r in self._load():
            if r.get("id") == sub_id:
                return Subscription(**r)
        return None

    def delete(self, sub_id: str, chat_id: Optional[str] = None) -> bool:
        rows = self._load()
        kept = [r for r in rows
                if not (r.get("id") == sub_id and (chat_id is None or r.get("chat_id") == chat_id))]
        if len(kept) == len(rows):
            return False
        self._save(kept)
        return True

    def all_active(self) -> list[Subscription]:
        return [s for s in self.list() if s.active]

    def mark_sent(self, sub_id: str, date_iso: str) -> None:
        rows = self._load()
        changed = False
        for r in rows:
            if r.get("id") == sub_id:
                r["last_sent"] = date_iso
                changed = True
        if changed:
            self._save(rows)

    def count(self, chat_id: Optional[str] = None) -> int:
        return len(self.list(chat_id))
