"""Verify sheet UC10 — insight & NL Q&A (structure + graceful degradation).

UC10 plans + synthesises via the LLM, so a full run needs LLM env (test that live
through the server). Offline this asserts: the use case is discovered, excludes
itself/hypothesis_check from the plannable set, and degrades cleanly (a planning
note + error, no crash) when the LLM is unavailable.

Run: ./venv/bin/python tests/verify_uc10_insight_qa.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.deps import Deps  # noqa: E402
from core.registry import discover_use_cases  # noqa: E402
from storage.snapshots import SnapshotStore  # noqa: E402
from usecases.uc10_insight_qa import _PLANNABLE, InsightQAUseCase  # noqa: E402


def main():
    assert "uc10_insight_qa" in discover_use_cases(), "use case not auto-discovered"
    assert "uc10_insight_qa" not in _PLANNABLE, "uc10 must not plan itself (recursion)"
    assert "hypothesis_check" not in _PLANNABLE, "hypothesis_check must be excluded from plan"
    print(f"PASS: discovered; plannable = {list(_PLANNABLE)}")

    # No LLM env -> planning can't run -> clean error (no crash).
    deps = Deps(connectors=[], storage=SnapshotStore(tempfile.mkdtemp()))
    res = InsightQAUseCase().run({"question": "ZaloPay nên cải thiện gì để cạnh tranh tốt hơn?"}, deps)
    print(f"no-LLM result: error={res.get('error')!r} notes={res.get('notes')}")
    assert res.get("error"), "should report it could not plan without an LLM"
    print("PASS: degrades cleanly without the LLM")


if __name__ == "__main__":
    main()
    print("\nALL OK")
