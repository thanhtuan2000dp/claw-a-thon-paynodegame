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
    rank: Optional[int] = None  # top-chart position (sheet UC1); None = not in chart
    # Current version's store changelog at capture time. Stores expose only the
    # latest version's notes, so accruing them per snapshot is how the agent builds
    # a per-version changelog history for free (sheet UC3). Optional + defaulted so
    # older snapshot lines (written before this field) still load.
    release_notes: Optional[str] = None


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

    def save_table(self, kind: str, app_id: str, store: str, rows: list[dict],
                   captured_at: Optional[str] = None) -> str:
        """Persist a raw table (e.g. UC1 metadata rows, UC2 reviews) as JSON so
        downstream use cases (dashboard, weakness mining) can reuse it without
        re-crawling. Written under ``data/<kind>/`` next to the snapshot dir.
        Returns the file path. Ephemeral in a container — same caveat as snapshots."""
        parent = os.path.dirname(self.base_dir) or "."
        out_dir = os.path.join(parent, kind)
        os.makedirs(out_dir, exist_ok=True)
        safe = f"{store}_{app_id}".replace("/", "_").replace("..", "_")
        suffix = f"_{captured_at}" if captured_at else ""
        path = os.path.join(out_dir, f"{safe}{suffix}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)
        return path

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
