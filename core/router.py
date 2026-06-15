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
    "khoảng", "dạo", "trở", "lại", "month", "months", "week", "weeks", "day", "days", "year", "years",
    "last", "past", "recent", "recently", "this",
    # connective / filler words ("đánh giá VỀ X", "đối với X")
    "về", "đối", "với",
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

# Greeting / "what can you do" detection -> the `help` use case. Caught BEFORE the
# LLM router so a greeting never gets misrouted into an app analysis (and needs no
# LLM call). Kept tight to avoid swallowing real queries.
_GREETINGS = {"hi", "hello", "helo", "hey", "yo", "hallo", "chào", "xin chào", "chào bạn",
              "alo", "halo", "hí", "start", "/start"}
_HELP_WORDS = {"help", "trợ giúp", "hướng dẫn", "menu", "bắt đầu"}
_HELP_PHRASES = (
    "làm được gì", "làm được những gì", "làm gì được", "có thể làm gì", "giúp được gì",
    "giúp gì được", "bạn là ai", "bạn là gì", "agent là gì", "dùng thế nào", "dùng như thế nào",
    "dùng ra sao", "hoạt động thế nào", "tính năng gì", "có gì",
    "what can you do", "what can u do", "who are you", "what are you", "how to use",
    "how do you work", "what do you do", "your capabilities", "list features",
)


def _looks_like_help(message: str) -> bool:
    """True for a bare greeting or a meta question about the assistant itself."""
    m = message.lower().strip(" \t\n?!.…")
    if not m:
        return False
    if m in _GREETINGS or m in _HELP_WORDS:
        return True
    if len(m.split()) <= 4 and any(m == g or m.startswith(g + " ") for g in _GREETINGS):
        return True
    return any(p in m for p in _HELP_PHRASES)


def _detect_store(low: str):
    if any(h in low for h in _IOS_HINTS):
        return "ios"
    if any(h in low for h in _ANDROID_HINTS):
        return "android"
    return None


# Duration phrases -> analysis window in days (used by UC2 / UC6). E.g. "1 năm", "6 tháng".
_UNIT_DAYS = {"năm": 365, "year": 365, "years": 365, "tháng": 30, "month": 30, "months": 30,
              "tuần": 7, "week": 7, "weeks": 7, "ngày": 1, "day": 1, "days": 1}
_WINDOW_RE = re.compile(r"(\d+)\s*(năm|years?|tháng|months?|tuần|weeks?|ngày|days?)")


def _parse_window_days(low: str):
    """Pull an analysis window (in days) out of a duration phrase, else None.
    "1 năm trở lại đây" -> 365, "6 tháng" -> 180, "2 tuần" -> 14."""
    m = _WINDOW_RE.search(low)
    if m:
        return max(1, min(int(m.group(1)) * _UNIT_DAYS[m.group(2)], 3650))  # cap ~10y
    if "năm qua" in low or "năm nay" in low:
        return 365
    if "tháng qua" in low or "tháng này" in low:
        return 30
    if "tuần qua" in low or "tuần này" in low:
        return 7
    return None


def _heuristic_route(message: str):
    """FALLBACK ONLY (used when the LLM router is unavailable). Keyword/stopword
    routing — intent words pick the action, command/time/platform words are stripped
    to guess the app name, durations -> window_days. Brittle by nature; the LLM path
    (Router._route_nl) is the primary router. Returns (action, params) or None."""
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
    # A platform mention narrows the store; a duration phrase sets the window
    # (both are also stripped from the app name below).
    store = _detect_store(low)
    window_days = _parse_window_days(low)

    def params(app: str) -> dict:
        p = {"app": app}
        if store:
            p["store"] = store
        if window_days:
            p["window_days"] = window_days
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
        # session_id -> {app, store, use_case}: cross-turn context so a follow-up that
        # omits the app ("tôi đoán điều này do lỗi gần đây") reuses the last one.
        # In-memory (per server process) — for durable/multi-instance, back with Memory.
        self._recent: dict[str, dict] = {}

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
        session_id = getattr(context, "session_id", None) or payload.get("session_id") or "default"

        if not action and message and "help" in self.use_cases and _looks_like_help(message):
            # Greeting / "what can you do" — answer with capabilities + suggestions
            # instead of routing to an analysis (and without spending an LLM call).
            action = "help"
            params.setdefault("message", message)
        elif not action and message:
            # LLM-first: the model picks the action and extracts params (app, store,
            # window, dates), using recent session context to resolve follow-ups that
            # omit the app or refer back ("điều này", "nó"). Falls back to the keyword
            # heuristic only when the LLM is unavailable.
            action, extracted = self._route_nl(message, self._recent.get(session_id))
            # explicit params win over extracted ones
            params = {**extracted, **params}
            # keep the raw user text available for use cases that need it verbatim
            # (uc10 question, hypothesis_check statement) — never overrides extracted.
            params.setdefault("message", message)

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
        result = uc.run(params, self.deps, context)
        self._remember(session_id, action, result)
        return result

    def _remember(self, session_id: str, action: str | None, result: dict) -> None:
        """Stash the resolved app/store after a successful turn so a later follow-up
        that omits them can reuse them via _route_nl. A need-context / errored turn
        leaves the prior context intact (no useful app to remember)."""
        if not session_id or not isinstance(result, dict) or result.get("error"):
            return
        if result.get("mode") == "cross_platform":
            name = None
            for p in result.get("platforms", {}).values():
                if isinstance(p, dict) and not p.get("error"):
                    name = (p.get("app") or {}).get("name") or name
            app, store = name or result.get("app_query"), "both"
        else:
            app = (result.get("app") or {}).get("name")
            store = (result.get("app") or {}).get("store")
        if app:
            self._recent[session_id] = {
                "app": app, "store": store, "use_case": result.get("use_case") or action,
            }

    def _route_nl(self, message: str, recent: dict | None = None) -> tuple[str | None, dict]:
        """Primary NL router: the LLM picks the action and extracts params from the
        action catalog. Robust to phrasing/language/time-expressions (no keyword
        lists). ``recent`` carries the prior turn's {app, store, use_case} so a
        follow-up that omits the app resolves against it. Falls back to the keyword
        heuristic only if the LLM is unavailable (MaaS down/slow or unparseable
        output), so routing still degrades gracefully."""
        names = list(self.use_cases)
        if not names:
            return None, {}
        catalog_lines = "\n".join(f"- {uc.name}: {uc.description}" for uc in self.use_cases.values())
        context_block = ""
        if recent and recent.get("app"):
            context_block = (
                "Recent conversation context — use it to resolve a follow-up that omits "
                "the app/platform or refers back (\"điều này\", \"nó\", \"app đó\", \"this\", \"vậy\"): "
                f"app={recent['app']}, store={recent.get('store') or 'both'}, "
                f"last analysis={recent.get('use_case')}. Reuse this app AND store/platform "
                "UNLESS the new message clearly names a different one. If it is a hypothesis, "
                "rewrite params.statement to be self-contained — naming this app, the platform "
                "(iOS/Android per store above), and the metric in context (e.g. reviews/rating).\n\n"
            )
        prompt = (
            "You route a user's message to ONE app-analytics action and extract its parameters.\n"
            "Choose the action whose description best matches the user's intent — the "
            "descriptions say what each action is and is NOT for.\n"
            f"Actions:\n{catalog_lines}\n\n"
            + context_block
            + "Extract into params (omit a key if absent):\n"
            "- app: the app name, OR a store id copied VERBATIM (Android package e.g. "
            "com.zing.zalo, or iOS numeric trackId). Drop filler words ('ứng dụng', 'về', "
            "'phân tích', 'app'). NEVER invent or guess an app — use ONLY an app explicitly "
            "named in the message or in the recent context above; if there is none, OMIT app.\n"
            '- store: "ios", "android", or "both" (default "both" if no platform is named).\n'
            '- window_days: integer days from any time phrase — "1 năm"/"1 year"=365, '
            '"6 tháng"=180, "2 tuần"=14, "tháng này"/"last month"=30.\n'
            "- date_from / date_to: ISO dates ONLY if the user gives explicit calendar dates.\n"
            "- country: 2-letter code only if explicitly mentioned.\n"
            "- statement: for hypothesis_check, the full context-resolved claim text.\n\n"
            f'User message: "{message}"\n\n'
            'Return ONLY JSON: {"action": "<one of the action names>", "params": {...}}.'
        )
        try:
            data = self.deps.llm.complete_json(prompt)
            action = data.get("action") if isinstance(data, dict) else None
            params = data.get("params", {}) if isinstance(data, dict) else {}
            if not isinstance(params, dict):
                params = {}
            if action in self.use_cases:
                # Reliability: if the message literally contains a store id, trust the
                # verbatim regex over the model's copy (LLMs can mangle long ids).
                low = message.lower()
                idm = re.search(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+){2,}", low) or re.search(r"\b\d{6,}\b", low)
                if idm:
                    params["app"] = idm.group(0)
                return action, params
        except Exception:  # noqa: BLE001 - MaaS down/slow or bad JSON -> heuristic fallback
            pass
        # Fallback (LLM unavailable): keyword heuristic, else unresolved.
        return _heuristic_route(message) or ((names[0] if len(names) == 1 else None), {"app": message})
