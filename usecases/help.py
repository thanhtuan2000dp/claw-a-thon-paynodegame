"""Greeting / help — what Veridex can do, with suggested prompts.

When the user just says hello or asks what the agent can do (rather than asking
about a specific app), this returns a short capability overview plus clickable
example prompts — instead of routing to an analysis that has no app to work on.
The router short-circuits obvious greetings here (see ``core/router._looks_like_help``)
and the LLM router can also pick it for fuzzier phrasings.
"""

from __future__ import annotations

from core.lang import detect_lang
from usecases.base import UseCase

_CAPS_VI = [
    ("📄 Thông tin & xếp hạng store", "metadata, hạng mục, giá, rank top-chart"),
    ("💬 Review & cảm xúc", "phân bố sao, chủ đề khen/chê, trích dẫn"),
    ("📈 KPI & xu hướng", "rating/rank/lượt đánh giá theo thời gian"),
    ("🚀 Tác động bản cập nhật", "rating trước/sau release, vấn đề nổi lên"),
    ("🆚 So sánh đối thủ", "rank/rating/giá so với app cùng nhóm"),
    ("⚠️ Điểm yếu đối thủ", "gom phàn nàn của đối thủ thành cơ hội"),
    ("🔔 Cảnh báo bất thường", "tụt rating/rank, đổi version — gửi qua Telegram"),
    ("❓ Hỏi đáp tổng hợp", "câu hỏi mở, tôi tự gộp nhiều phân tích"),
    ("🔬 Kiểm chứng giả thuyết", "nêu giả thuyết, tôi kiểm bằng dữ liệu"),
]
_SUGG_VI = [
    "Phân tích review gần đây của Zalo",
    "So sánh Liên Quân Mobile với game cùng thể loại",
    "MoMo có bất thường gì không?",
    "Kiểm tra sức khỏe bản cập nhật mới của Genshin Impact",
    "Xu hướng rating của TikTok 3 tháng qua",
]
_CAPS_EN = [
    ("📄 Store info & ranking", "metadata, category, price, top-chart rank"),
    ("💬 Reviews & sentiment", "star split, praise/complaint themes, quotes"),
    ("📈 KPIs & trends", "rating/rank/#ratings over time"),
    ("🚀 Release impact", "rating before/after a release, emerging issues"),
    ("🆚 Competitor comparison", "rank/rating/price vs same-category apps"),
    ("⚠️ Competitor weaknesses", "cluster rivals' complaints into opportunities"),
    ("🔔 Anomaly alerts", "rating/rank drops, version changes — via Telegram"),
    ("❓ Free-form Q&A", "open questions, I combine analyses"),
    ("🔬 Hypothesis check", "state a claim, I test it against the data"),
]
_SUGG_EN = [
    "Analyze recent reviews of Instagram",
    "Compare Genshin Impact with similar games",
    "Any anomalies for Candy Crush?",
    "Check the release health of WhatsApp's latest update",
    "Rating trend of Spotify over the last 3 months",
]


class HelpUseCase(UseCase):
    name = "help"
    description = (
        "Greeting, small talk, or a META question about the assistant itself — e.g. "
        "'xin chào', 'hello', 'bạn là ai', 'bạn/agent làm được gì', 'giúp được gì', 'help', "
        "'hướng dẫn', 'how to use', 'what can you do', 'bắt đầu thế nào'. Returns a capability "
        "overview + suggested prompts. Use this ONLY when the user is NOT asking about a "
        "specific app, metric, or hypothesis."
    )
    input_schema = {}

    def run(self, params: dict, deps, context=None) -> dict:
        lang = (params.get("lang") or detect_lang(params.get("message") or "")).lower()
        vi = lang != "en"
        caps = _CAPS_VI if vi else _CAPS_EN
        return {
            "use_case": self.name,
            "lang": lang,
            "answer": ("Mình phân tích tín hiệu công khai trên App Store / Google Play — cả "
                       "ứng dụng lẫn game — để hỗ trợ quyết định sản phẩm. Mình có thể giúp:" if vi else
                       "I analyze public App Store / Google Play signals — both apps and games — "
                       "to support product decisions. I can help with:"),
            "capabilities": [{"title": t, "desc": d} for t, d in caps],
            "suggestions": _SUGG_VI if vi else _SUGG_EN,
            "summary": ("Hỏi tự nhiên (VI/EN) hoặc bấm một gợi ý bên dưới để bắt đầu." if vi else
                        "Ask naturally (VI/EN) or tap a suggestion below to start."),
        }
