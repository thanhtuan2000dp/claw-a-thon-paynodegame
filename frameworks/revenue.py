"""Revenue claim framework: "feature/build X changed revenue".

Decomposes into acquisition vs monetization levers, gated by a necessary
condition (revenue actually moved). Revenue/download signals need the `downloads`
capability (Sensor Tower with the right scope); when unavailable the engine marks
those sub-hypotheses untestable and the verdict says so honestly.
"""

from __future__ import annotations

from .base import (
    SIG_DOWNLOAD_DELTA,
    SIG_FEATURE_MENTION,
    SIG_NEG_SHARE,
    SIG_REVENUE_DELTA,
    SIG_TIMING,
    Framework,
    SubHypothesis,
)


class RevenueFramework(Framework):
    metric = "revenue"

    def sub_hypotheses(self, claim: dict, lang: str = "en") -> list[SubHypothesis]:
        vi = lang == "vi"
        cause = claim.get("cause") or ("the feature" if not vi else "tính năng này")
        return [
            SubHypothesis(
                id="H1",
                statement=(
                    "Doanh thu thực sự thay đổi theo chiều được nêu sau build so với baseline." if vi else
                    "Revenue actually moved in the claimed direction in the window after the build vs the baseline."
                ),
                signal=SIG_REVENUE_DELTA,
                data_need="downloads",
                necessary=True,
            ),
            SubHypothesis(
                id="H2",
                statement=(
                    "Sự thay đổi doanh thu xảy ra đúng thời điểm phát hành build này (không phải xu hướng từ trước)." if vi else
                    "The revenue move aligns in time with this build's release (not a pre-existing trend)."
                ),
                signal=SIG_TIMING,
                data_need="metadata",
            ),
            SubHypothesis(
                id="H3",
                statement=(
                    "Sự thay đổi do monetization, không phải chỉ do lượt cài đặt tăng trong cùng khoảng thời gian." if vi else
                    "The move is monetization-driven, not merely acquisition (downloads) rising in the same window."
                ),
                signal=SIG_DOWNLOAD_DELTA,
                data_need="downloads",
            ),
            SubHypothesis(
                id="H4",
                statement=(
                    f"Người dùng đề cập đến '{cause}' tích cực sau khi phát hành (tín hiệu adoption)." if vi else
                    f"Users reference '{cause}' positively after the release (adoption signal)."
                ),
                signal=SIG_FEATURE_MENTION,
                data_need="reviews",
            ),
            SubHypothesis(
                id="H5",
                statement=(
                    "Không có suy giảm chất lượng rõ rệt (review tiêu cực tăng) giải thích tốt hơn cho sự thay đổi." if vi else
                    "No dominant quality regression (rising negative reviews) better explains the change."
                ),
                signal=SIG_NEG_SHARE,
                data_need="reviews",
            ),
        ]
