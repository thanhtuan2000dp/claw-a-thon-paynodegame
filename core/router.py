"""Request router.

Dispatches an incoming request to a use case, two ways:
  • explicit:  {"action": "uc6_version_impact", "params": {...}}
  • natural:   {"message": "kiểm tra sức khỏe bản cập nhật Instagram"}  -> LLM picks action + params

Adding a use case to the ``usecases`` package makes it routable automatically.
"""

from __future__ import annotations

import re

from core.registry import discover_use_cases

# Markers that signal a causal claim -> Hypothesis Checker.
_HYPO_MARKERS = (
    "tôi nghĩ", "mình nghĩ", "tôi cho rằng", "tao nghĩ", "i think", "i believe", "i guess",
    "làm tăng", "làm giảm", "tăng do", "giảm do", "vì lỗi", "do lỗi", "nhờ tính năng",
    "because", "caused", "is due to", "drove",
)
# Intent keywords (matched as substrings on the lowercased message) that steer the
# heuristic to a specific use case. Review/sentiment is checked before metadata
# (the more specific ask); neither present → the release-health default.
_REVIEW_INTENT = (
    "review", "đánh giá", "nhận xét", "sentiment", "cảm xúc", "phàn nàn", "than phiền",
    "feedback", "bình luận", "comment", "ý kiến", "góp ý", "khen", "chê",
    "complaint", "praise", "opinion",
)
_META_INTENT = (
    "metadata", "thông tin", "rank", "xếp hạng", "thứ hạng", "bảng xếp hạng", "danh mục",
    "category", "screenshot", "ảnh chụp", "mô tả", "description", "icon", "thông số", "info",
)

# Command words to strip when extracting an app name from a query.
_STOPWORDS = {
    "kiểm", "tra", "bản", "cập", "nhật", "mới", "nhất", "gần", "đây", "sức", "khỏe", "phân",
    "tích", "của", "app", "ứng", "dụng", "đánh", "giá", "xem", "cho", "tôi", "review", "reviews",
    "tình", "hình", "trên", "thế", "nào", "ra", "sao",
    "check", "the", "latest", "update", "release", "health", "analyze", "analyse", "for", "of",
    "how", "is", "doing", "on", "status", "a", "an", "please",
    # time-window words — "1 tháng gần đây", "tuần qua", "tháng này", "last month", ...
    # (standalone digits are dropped separately, so "1 tháng" leaves nothing behind)
    "tháng", "tuần", "ngày", "năm", "qua", "vừa", "rồi", "này", "nay", "hôm", "trong",
    "khoảng", "dạo", "month", "months", "week", "weeks", "day", "days", "year", "years",
    "last", "past", "recent", "recently", "this",
    # intent words (so review/metadata keywords don't leak into the app name)
    "metadata", "sentiment", "feedback", "comment", "comments", "info", "rank", "ranking",
    "category", "screenshot", "screenshots", "icon", "description", "store", "play",
    "nhận", "xét", "phàn", "nàn", "than", "phiền", "cảm", "xúc", "bình", "luận", "khen", "chê",
    "thông", "tin", "danh", "mục", "xếp", "hạng", "thứ", "bảng", "mô", "tả", "ảnh", "chụp",
    "góp", "ý", "kiến", "complaint", "complaints", "praise", "opinion", "opinions",
    # platform words (stripped from the app name; also used to set `store`)
    "ios", "iphone", "ipad", "android", "appstore", "playstore", "googleplay", "apple", "google",
}

# Platform mentions -> store param. Checked as substrings on the lowercased message.
_IOS_HINTS = ("ios", "iphone", "ipad", "app store", "appstore", "apple store")
_ANDROID_HINTS = ("android", "google play", "play store", "playstore", "ch play", "chplay")


def _detect_store(low: str):
    if any(h in low for h in _IOS_HINTS):
        return "ios"
    if any(h in low for h in _ANDROID_HINTS):
        return "android"
    return None


def _heuristic_route(message: str):
    """Route + extract params WITHOUT an LLM call for common phrasings, so the slow
    MaaS routing call is off the critical path. Returns (action, params) or None
    (None -> fall back to LLM routing)."""
    low = message.lower()
    if any(m in low for m in _HYPO_MARKERS):
        return ("hypothesis_check", {"statement": message})
    # Intent -> action. Review/sentiment beats metadata when both appear (more
    # specific); neither present -> the release-health default (sheet UC6).
    if any(k in low for k in _REVIEW_INTENT):
        action = "uc2_reviews_sentiment"
    elif any(k in low for k in _META_INTENT):
        action = "uc1_store_metadata"
    else:
        action = "uc6_version_impact"
    # A platform mention narrows the store (and is stripped from the app name below).
    store = _detect_store(low)

    def params(app: str) -> dict:
        p = {"app": app}
        if store:
            p["store"] = store
        return p

    # Explicit store id: Android package (com.x.y) or iOS trackId (long digits).
    pkg = re.search(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+){2,}", low)
    if pkg:
        return (action, params(pkg.group(0)))
    tid = re.search(r"\b\d{6,}\b", low)
    if tid:
        return (action, params(tid.group(0)))
    # Strip command words -> the remaining tokens are the app name.
    tokens = re.findall(r"[^\s,.;:!?()]+", message)
    kept = [t for t in tokens if t.lower() not in _STOPWORDS and not t.isdigit()]
    app = " ".join(kept).strip()
    if app and len(app) <= 40:
        return (action, params(app))
    return None


class Router:
    def __init__(self, deps):
        self.deps = deps
        self.use_cases = {name: cls() for name, cls in discover_use_cases().items()}

    def catalog(self) -> list[dict]:
        return [
            {"action": uc.name, "description": uc.description, "params": uc.input_schema}
            for uc in self.use_cases.values()
        ]

    def handle(self, payload: dict, context=None) -> dict:
        from core.lang import detect_lang

        action = payload.get("action")
        params = dict(payload.get("params", {}))
        message = payload.get("message")

        if not action and message:
            # Heuristic first (no LLM, instant); fall back to LLM routing only if it can't decide.
            action, extracted = _heuristic_route(message) or self._route_nl(message)
            # explicit params win over heuristic/LLM-extracted ones
            params = {**extracted, **params}

        # Auto-detect response language from the user's own words (full message is
        # the best signal; fall back to any text params). Use cases localise output.
        if "lang" not in params:
            params["lang"] = detect_lang(
                message or "", params.get("app", ""), params.get("statement", "")
            )

        if not action:
            return {
                "error": "Provide 'action' + 'params', or a natural-language 'message'.",
                "available_actions": self.catalog(),
            }

        uc = self.use_cases.get(action)
        if uc is None:
            return {
                "error": f"Unknown action '{action}'.",
                "available_actions": self.catalog(),
            }
        return uc.run(params, self.deps, context)

    def _route_nl(self, message: str) -> tuple[str | None, dict]:
        names = list(self.use_cases)
        if not names:
            return None, {}
        catalog_lines = "\n".join(
            f'- {uc.name}: {uc.description} params={list(uc.input_schema)}'
            for uc in self.use_cases.values()
        )
        prompt = (
            "Pick the best action for the user's message and extract parameters.\n"
            f"Actions:\n{catalog_lines}\n\n"
            f'User message: "{message}"\n\n'
            'Return ONLY JSON: {"action": "<one of the action names>", "params": {...}}. '
            "Extract any app name, store (ios/android), country, or window into params."
        )
        try:
            data = self.deps.llm.complete_json(prompt)
        except Exception:  # noqa: BLE001 - if routing LLM fails, fall back
            # Single-use-case default; otherwise leave unresolved.
            return (names[0] if len(names) == 1 else None), {"app": message}
        action = data.get("action") if isinstance(data, dict) else None
        params = data.get("params", {}) if isinstance(data, dict) else {}
        if action not in self.use_cases:
            action = names[0] if len(names) == 1 else None
        return action, params if isinstance(params, dict) else {}
