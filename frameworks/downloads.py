"""Downloads / acquisition claim framework: "build X changed installs".

Download signals need the `downloads` capability (Sensor Tower scope); the engine
marks them untestable when unavailable.
"""

from __future__ import annotations

from .base import (
    SIG_DOWNLOAD_DELTA,
    SIG_RATING_DELTA,
    SIG_TIMING,
    Framework,
    SubHypothesis,
)


class DownloadsFramework(Framework):
    metric = "downloads"

    def sub_hypotheses(self, claim: dict, lang: str = "en") -> list[SubHypothesis]:
        vi = lang == "vi"
        return [
            SubHypothesis(
                id="H1",
                statement=(
                    "Ước tính lượt cài đặt thay đổi theo chiều được nêu sau build so với baseline." if vi else
                    "Install estimate moved in the claimed direction after the build vs baseline."
                ),
                signal=SIG_DOWNLOAD_DELTA,
                data_need="downloads",
                necessary=True,
            ),
            SubHypothesis(
                id="H2",
                statement=(
                    "Sự thay đổi xảy ra đúng thời điểm phát hành build này." if vi else
                    "The move aligns in time with this build's release."
                ),
                signal=SIG_TIMING,
                data_need="metadata",
            ),
            SubHypothesis(
                id="H3",
                statement=(
                    "Chất lượng không suy giảm (rating không giảm) — yếu tố có thể ảnh hưởng đến acquisition." if vi else
                    "Reception did not worsen (rating not dropping), which could confound acquisition."
                ),
                signal=SIG_RATING_DELTA,
                data_need="reviews",
            ),
        ]
