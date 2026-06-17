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

    def sub_hypotheses(self, claim: dict, lang: str = "en") -> list[SubHypothesis]:
        cause = claim.get("cause") or ("the change" if lang == "en" else "thay đổi này")
        vi = lang == "vi"
        return [
            SubHypothesis(
                id="H1",
                statement=(
                    "Rating review thay đổi theo chiều được nêu sau build so với trước." if vi else
                    "Review rating moved in the claimed direction after the build vs before."
                ),
                signal=SIG_RATING_DELTA,
                data_need="reviews",
                necessary=True,
            ),
            SubHypothesis(
                id="H2",
                statement=(
                    "Xu hướng rating tổng thể của store nhất quán (kiểm tra qua snapshots)." if vi else
                    "The overall store rating trend agrees (cross-check via snapshots)."
                ),
                signal=SIG_METRIC_RATING,
                data_need="metadata",
            ),
            SubHypothesis(
                id="H3",
                statement=(
                    "Tỷ lệ review tiêu cực thay đổi sau build (nguyên nhân được nêu)." if vi else
                    "The mix of negative reviews shifted after the build (the proposed cause)."
                ),
                signal=SIG_NEG_SHARE,
                data_need="reviews",
            ),
            SubHypothesis(
                id="H4",
                statement=(
                    f"Review đề cập đến '{cause}' sau khi phát hành." if vi else
                    f"Reviews reference '{cause}' after the release."
                ),
                signal=SIG_FEATURE_MENTION,
                data_need="reviews",
            ),
            SubHypothesis(
                id="H5",
                statement=(
                    "Sự thay đổi xảy ra đúng thời điểm build này (không phải xu hướng từ trước)." if vi else
                    "The shift aligns in time with this build (not a pre-existing trend)."
                ),
                signal=SIG_TIMING,
                data_need="metadata",
            ),
        ]
