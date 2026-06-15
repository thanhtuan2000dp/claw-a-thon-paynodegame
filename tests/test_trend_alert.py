"""Offline tests for UC9 anomaly logic with a fake metadata connector + seeded
snapshots (no network/LLM): a prior higher rating yields a rating-drop alert; no
history yields a baseline-seeded result."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.base import CAP_METADATA, AppDataConnector, AppMetadata  # noqa: E402
from core.deps import Deps  # noqa: E402
from storage.snapshots import Snapshot, SnapshotStore  # noqa: E402
from usecases.uc9_trend_alert import TrendAlertUseCase  # noqa: E402


class FakeMeta(AppDataConnector):
    name = "fakemeta"
    stores = {"ios"}

    def capabilities(self):
        return {CAP_METADATA}

    def get_metadata(self, app_id, store="ios", country=None, lang=None):
        return AppMetadata(app_id=app_id, name="FakeApp", store="ios",
                           version="2.0", avg_rating=1.95, rating_count=350000)


def _deps(store):
    return Deps(connectors=[FakeMeta()], storage=store)


def test_rating_drop_alert():
    st = SnapshotStore(tempfile.mkdtemp())
    st.save(Snapshot(captured_at="2026-06-01", app_id="999", store="ios",
                     version="1.0", avg_rating=2.5, rating_count=349000, rank=None))
    res = TrendAlertUseCase().run({"app": "999", "store": "ios", "lang": "vi"}, _deps(st))
    assert res.get("status") == "alert", res
    assert any(a["type"] == "rating_drop" and a["severity"] == "high" for a in res["alerts"]), res["alerts"]


def test_baseline_seeded_without_history():
    st = SnapshotStore(tempfile.mkdtemp())
    res = TrendAlertUseCase().run({"app": "999", "store": "ios", "lang": "vi"}, _deps(st))
    assert res.get("status") == "baseline_seeded", res
    assert res["alerts"] == []
