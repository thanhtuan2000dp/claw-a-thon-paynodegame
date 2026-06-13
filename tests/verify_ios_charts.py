"""Verify the free iOS charts ranking connector against the live Apple feed.

Run: ./venv/bin/python tests/verify_ios_charts.py
Never needs a token or LLM. Skips the live asserts gracefully if offline.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.base import CAP_RANKING, ConnectorError, RankPoint  # noqa: E402
from connectors.ios_charts import IosChartsConnector  # noqa: E402


def test_contract():
    c = IosChartsConnector(country="us")
    assert c.name == "ios_charts"
    assert c.stores == {"ios"}
    assert c.capabilities() == {CAP_RANKING}
    assert c.supports(CAP_RANKING, "ios")
    assert not c.supports(CAP_RANKING, "android")
    assert not c.supports("reviews", "ios")
    assert c.is_available()
    print("contract: OK")


def test_live():
    c = IosChartsConnector(country="us", limit=50)
    today = datetime.now()
    try:
        chart = c._fetch_chart("top-free", "us")
    except ConnectorError as e:
        print(f"live: SKIPPED (offline?): {e}")
        return
    assert chart, "top-free chart came back empty"
    top = chart[0]
    top_id = str(top.get("id"))
    print(f"live: top-free #1 = {top.get('name')} (id={top_id})")

    # An app that IS in the chart resolves to its 1-based position.
    rp = c.get_ranking(top_id, "ios", "top-free", today)
    assert isinstance(rp, RankPoint)
    assert rp.rank == 1, f"expected rank 1 for chart leader, got {rp.rank}"
    assert rp.category == "top-free"
    print(f"live: get_ranking(chart leader) -> rank {rp.rank} ✓")

    # Friendly alias maps to a feed slug; unknown category falls back to top-free.
    rp2 = c.get_ranking(top_id, "ios", "paid", today)
    assert rp2.category == "top-paid"
    rp_unknown = c.get_ranking(top_id, "ios", "some-bogus-cat", today)
    assert rp_unknown.category == "top-free"
    print(f"live: alias 'paid' -> '{rp2.category}', unknown -> '{rp_unknown.category}' ✓")

    # An app not in the (small) chart -> rank None, never an exception.
    rp3 = c.get_ranking("0000000000", "ios", "top-free", today)
    assert rp3.rank is None
    print("live: unknown app -> rank None ✓")


if __name__ == "__main__":
    test_contract()
    test_live()
    print("\nALL OK")
