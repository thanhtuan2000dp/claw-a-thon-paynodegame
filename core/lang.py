"""Language detection + market mapping.

Auto-detects Vietnamese vs English from user text, and maps the language to a
store market (country/lang) so a Vietnamese query analyses the VN store with
Vietnamese reviews, and English the US store. Keeps the agent genuinely bilingual
without the user having to specify anything.
"""

from __future__ import annotations

import re

# Characters unique to Vietnamese (diacritics + đ/ă/â/ê/ô/ơ/ư). Their presence is
# a high-precision signal the text is Vietnamese.
_VI_CHARS = re.compile(
    r"[ăâđêôơưĂÂĐÊÔƠƯàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]",
    re.IGNORECASE,
)

# Market per language: (store country code, review language code).
_MARKETS = {"vi": ("vn", "vi"), "en": ("us", "en")}


def detect_lang(*texts: str) -> str:
    """Return 'vi' if any provided text contains Vietnamese characters, else 'en'."""
    for t in texts:
        if t and _VI_CHARS.search(t):
            return "vi"
    return "en"


def market_for(lang: str) -> tuple[str, str]:
    """(country, lang) for the given language; defaults to US/English."""
    return _MARKETS.get(lang, ("us", "en"))


def lang_name(lang: str) -> str:
    return "Vietnamese" if lang == "vi" else "English"
