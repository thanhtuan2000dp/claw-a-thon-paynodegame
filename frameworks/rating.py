"""Rating / quality claim framework: "build X changed the rating / reception".

This is the framework with the strongest free-data coverage (reviews on Android,
snapshot trend on iOS), so its sub-hypotheses lean on signals we can actually
measure.
"""

from __future__ import annotations

from .base import (
    SIG_FEATURE_MENTION,
    SIG_METRIC_RATING,
    SIG_NEG_SHARE,
    SIG_RATING_DELTA,
    SIG_TIMING,
    Framework,
    SubHypothesis,
)


class RatingFramework(Framework):
    metric = "rating"

    def sub_hypotheses(self, claim: dict) -> list[SubHypothesis]:
        cause = claim.get("cause") or "the change"
        return [
            SubHypothesis(
                id="H1",
                statement="Review rating moved in the claimed direction after the build vs before.",
                signal=SIG_RATING_DELTA,
                data_need="reviews",
                necessary=True,
            ),
            SubHypothesis(
                id="H2",
                statement="The overall store rating trend agrees (cross-check via snapshots).",
                signal=SIG_METRIC_RATING,
                data_need="metadata",
            ),
            SubHypothesis(
                id="H3",
                statement="The mix of negative reviews shifted after the build (the proposed cause).",
                signal=SIG_NEG_SHARE,
                data_need="reviews",
            ),
            SubHypothesis(
                id="H4",
                statement=f"Reviews reference '{cause}' after the release.",
                signal=SIG_FEATURE_MENTION,
                data_need="reviews",
            ),
            SubHypothesis(
                id="H5",
                statement="The shift aligns in time with this build (not a pre-existing trend).",
                signal=SIG_TIMING,
                data_need="metadata",
            ),
        ]
