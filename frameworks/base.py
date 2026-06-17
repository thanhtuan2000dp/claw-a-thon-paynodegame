"""Product-analytics framework library.

A Framework decomposes an executive's claim about a metric into falsifiable
**sub-hypotheses** a real analyst would test. The Hypothesis Checker picks the
framework matching the claim's metric, then tests each sub-hypothesis against the
data it can actually get (gating on connector capability) and aggregates a
calibrated verdict.

Pure Python — no network, no LLM — so frameworks are easy to read, test, extend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# Signals the Hypothesis Checker engine knows how to measure.
SIG_RATING_DELTA = "rating_delta"          # review rating before vs after release
SIG_METRIC_RATING = "metric_rating_delta"  # snapshot overall-rating trend (no reviews needed)
SIG_REVIEW_VELOCITY = "review_velocity"    # reviews/day before vs after
SIG_NEG_SHARE = "neg_share_shift"          # %<=2★ before vs after
SIG_FEATURE_MENTION = "feature_mention"    # reviews referencing the named cause/feature
SIG_TIMING = "timing_alignment"            # did the metric move align with the build date
SIG_REVENUE_DELTA = "revenue_delta"        # revenue estimate before vs after (needs downloads cap)
SIG_DOWNLOAD_DELTA = "download_delta"       # install estimate before vs after (needs downloads cap)


@dataclass
class SubHypothesis:
    id: str
    statement: str          # professional, falsifiable, human-readable
    signal: str             # one of SIG_* — what the engine measures
    data_need: str          # connector capability required ("reviews"|"downloads"|"metadata")
    necessary: bool = False  # if refuted, the whole claim is refuted (necessary condition)


class Framework(ABC):
    metric: str = "base"

    @abstractmethod
    def sub_hypotheses(self, claim: dict, lang: str = "en") -> list[SubHypothesis]:
        """Decompose the claim into testable sub-hypotheses."""


def framework_for(metric: str) -> "Framework | None":
    """Pick a framework by claim metric. Discovers all Framework subclasses."""
    import importlib
    import inspect
    import pkgutil

    import frameworks

    metric = (metric or "").lower()
    for _, modname, _ in pkgutil.iter_modules(frameworks.__path__):
        if modname in ("base", "__init__"):
            continue
        mod = importlib.import_module(f"frameworks.{modname}")
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, Framework) and obj is not Framework and obj.__module__ == mod.__name__:
                inst = obj()
                if inst.metric in metric or metric in inst.metric:
                    return inst
    return None
