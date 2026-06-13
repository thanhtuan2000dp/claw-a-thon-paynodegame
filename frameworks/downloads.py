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

    def sub_hypotheses(self, claim: dict) -> list[SubHypothesis]:
        return [
            SubHypothesis(
                id="H1",
                statement="Install estimate moved in the claimed direction after the build vs baseline.",
                signal=SIG_DOWNLOAD_DELTA,
                data_need="downloads",
                necessary=True,
            ),
            SubHypothesis(
                id="H2",
                statement="The move aligns in time with this build's release.",
                signal=SIG_TIMING,
                data_need="metadata",
            ),
            SubHypothesis(
                id="H3",
                statement="Reception did not worsen (rating not dropping), which could confound acquisition.",
                signal=SIG_RATING_DELTA,
                data_need="reviews",
            ),
        ]
