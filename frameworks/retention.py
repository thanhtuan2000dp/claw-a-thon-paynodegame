"""Retention claim framework: "build X changed retention/engagement".

Public app-store data has no direct retention metric, so this framework leans on
the available proxies (sustained rating, review velocity, complaint themes) and is
explicit that true retention needs internal cohort data.
"""

from __future__ import annotations

from .base import (
    SIG_NEG_SHARE,
    SIG_RATING_DELTA,
    SIG_REVIEW_VELOCITY,
    Framework,
    SubHypothesis,
)


class RetentionFramework(Framework):
    metric = "retention"

    def sub_hypotheses(self, claim: dict, lang: str = "en") -> list[SubHypothesis]:
        vi = lang == "vi"
        return [
            SubHypothesis(
                id="H1",
                statement=(
                    "Rating review duy trì ổn định sau build (proxy cho mức độ hài lòng/retention)." if vi else
                    "Sustained review rating after the build (proxy for satisfaction/retention)."
                ),
                signal=SIG_RATING_DELTA,
                data_need="reviews",
            ),
            SubHypothesis(
                id="H2",
                statement=(
                    "Lượng review không sụt giảm sau build (proxy cho mức độ sử dụng)." if vi else
                    "Review velocity did not collapse after the build (proxy for active usage)."
                ),
                signal=SIG_REVIEW_VELOCITY,
                data_need="reviews",
            ),
            SubHypothesis(
                id="H3",
                statement=(
                    "Không có đợt tăng đột biến khiếu nại về lỗi/xác thực sau build." if vi else
                    "No surge in churn-driving complaints (bugs/auth) after the build."
                ),
                signal=SIG_NEG_SHARE,
                data_need="reviews",
            ),
        ]
