"""Snapshot store — append-only daily metric snapshots per app.

Lets the agent build its own time series (rating/version over time) for apps it
has seen before. Backed by one JSON-lines file per app under ``base_dir``.

Container storage is ephemeral (snapshots reset on redeploy); for durable history
back this with AgentBase Memory or an external store. Fine for the demo.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class Snapshot:
    captured_at: str  # ISO date the snapshot was taken
    app_id: str
    store: str
    version: Optional[str] = None
    avg_rating: Optional[float] = None
    rating_count: Optional[int] = None
    current_version_release_date: Optional[str] = None


class SnapshotStore:
    def __init__(self, base_dir: str = "data/snapshots"):
        self.base_dir = base_dir

    def _path(self, app_id: str, store: str) -> str:
        safe = f"{store}_{app_id}".replace("/", "_").replace("..", "_")
        return os.path.join(self.base_dir, f"{safe}.jsonl")

    def save(self, snap: Snapshot) -> None:
        os.makedirs(self.base_dir, exist_ok=True)
        with open(self._path(snap.app_id, snap.store), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(snap), ensure_ascii=False) + "\n")

    def history(self, app_id: str, store: str) -> list[Snapshot]:
        path = self._path(app_id, store)
        if not os.path.exists(path):
            return []
        out: list[Snapshot] = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(Snapshot(**json.loads(line)))
        return out
