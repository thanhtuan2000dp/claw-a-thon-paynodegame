"""Markdown renderer for use-case results."""

from __future__ import annotations

from .base import OutputChannel

_VERDICT_ICON = {"healthy": "🟢", "regression": "🔴", "inconclusive": "🟡"}

_VERDICT_WORD = {
    "en": {"healthy": "HEALTHY", "regression": "REGRESSION", "inconclusive": "INCONCLUSIVE"},
    "vi": {"healthy": "KHỎE", "regression": "TỤT LÙI", "inconclusive": "CHƯA KẾT LUẬN"},
}

_UC6_LABELS = {
    "en": {
        "title": "Release Health", "build": "Build", "released": "Released", "verdict": "Verdict",
        "signal": "Signal", "before": "Before", "after": "After", "avg_rating": "Avg rating",
        "reviews_day": "Reviews/day", "neg_share": "Negative share", "sample": "Sample size",
        "snapshot_trend": "Snapshot trend", "since": "since", "overall_rating": "overall rating",
        "new_ratings": "new ratings", "overall_rating_cap": "Overall rating",
        "baseline_seeded": "baseline seeded — trend from next run",
        "top_complaints": "Top new complaints (post-release)", "notes": "Notes & caveats", "summary": "Summary",
    },
    "vi": {
        "title": "Sức khỏe bản cập nhật", "build": "Build", "released": "Phát hành", "verdict": "Kết luận",
        "signal": "Chỉ số", "before": "Trước", "after": "Sau", "avg_rating": "Rating TB",
        "reviews_day": "Review/ngày", "neg_share": "Tỷ lệ tiêu cực", "sample": "Cỡ mẫu",
        "snapshot_trend": "Xu hướng snapshot", "since": "từ", "overall_rating": "rating tổng",
        "new_ratings": "rating mới", "overall_rating_cap": "Rating tổng",
        "baseline_seeded": "đã lưu mốc — xu hướng hiện từ lần chạy sau",
        "top_complaints": "Than phiền mới (sau cập nhật)", "notes": "Ghi chú & lưu ý", "summary": "Tóm tắt",
    },
}


def _fmt(value, suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}{suffix}"
    return f"{value}{suffix}"


def _signed(value, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.{digits}f}"


class MarkdownOutput(OutputChannel):
    name = "markdown"

    def render(self, result: dict) -> str:
        uc = result.get("use_case")
        if uc == "hypothesis_check":
            return self._render_hypothesis(result)
        if uc == "uc6_version_impact":
            if result.get("mode") == "cross_platform":
                return self._render_uc6_cross(result)
            return self._render_uc6_single(result)
        if uc == "uc1_store_metadata":
            return self._render_cross(result, self._render_meta_single, "📦", "Store metadata", "Metadata cửa hàng") \
                if result.get("mode") == "cross_platform" else self._render_meta_single(result)
        if uc == "uc2_reviews_sentiment":
            return self._render_cross(result, self._render_reviews_single, "💬", "Reviews & sentiment", "Review & sentiment") \
                if result.get("mode") == "cross_platform" else self._render_reviews_single(result)
        # Generic fallback for other use cases.
        return result.get("summary", "```json\n" + str(result) + "\n```")

    # Shared cross-platform wrapper for the sheet UC1/UC2 use cases.
    def _render_cross(self, result: dict, single_fn, icon: str, title_en: str, title_vi: str) -> str:
        lang = result.get("lang", "en")
        title = title_vi if lang == "vi" else title_en
        lines = [f"# {icon} {title} — {result.get('app_query', '?')} (iOS + Android)", ""]
        if result.get("warning"):
            lines += [f"> {result['warning']}", ""]
        for key, label in (("ios", "🍎 iOS"), ("android", "🤖 Android")):
            p = result.get("platforms", {}).get(key, {})
            lines.append("---")
            if p.get("error"):
                lines.append(f"### {label}\n⚠️ {p['error']}")
            else:
                lines.append(single_fn(p))
            lines.append("")
        return "\n".join(lines)

    def _render_uc6_cross(self, result: dict) -> str:
        plats = result.get("platforms", {})
        lang = result.get("lang", "en")
        L = _UC6_LABELS.get(lang, _UC6_LABELS["en"])
        VW = _VERDICT_WORD.get(lang, _VERDICT_WORD["en"])
        lines = [f"# 📱 {L['title']} — {result.get('app_query', '?')} (iOS + Android)", ""]
        if result.get("warning"):
            lines.append(f"> {result['warning']}")
            lines.append("")
        order = [("ios", "🍎 iOS"), ("android", "🤖 Android")]
        # quick verdict line per platform
        for key, label in order:
            p = plats.get(key, {})
            if p.get("error"):
                lines.append(f"- {label}: ⚠️ {p['error']}")
            else:
                v = p.get("verdict", "inconclusive")
                icon = _VERDICT_ICON.get(v, "🟡")
                rel = p.get("release", {})
                lines.append(f"- {label}: {icon} **{VW.get(v, v.upper())}** · `{rel.get('version', '?')}` ({rel.get('release_date', '?')})")
        lines.append("")
        # full section per platform (single render carries its own '## … (store)' header)
        for key, label in order:
            p = plats.get(key, {})
            lines.append("---")
            if p.get("error"):
                lines.append(f"### {label}\n⚠️ {p['error']}")
            else:
                lines.append(self._render_uc6_single(p))
            lines.append("")
        return "\n".join(lines)

    def _render_uc6_single(self, result: dict) -> str:
        app = result.get("app", {})
        rel = result.get("release", {})
        sig = result.get("signals", {})
        verdict = result.get("verdict", "inconclusive")
        icon = _VERDICT_ICON.get(verdict, "🟡")
        lang = result.get("lang", "en")
        L = _UC6_LABELS.get(lang, _UC6_LABELS["en"])
        vword = _VERDICT_WORD.get(lang, _VERDICT_WORD["en"]).get(verdict, verdict.upper())

        lines: list[str] = []
        lines.append(f"## {icon} {L['title']} — {app.get('name', '?')} ({app.get('store', '')})")
        lines.append("")
        lines.append(
            f"**{L['build']}:** `{rel.get('version', '?')}` · "
            f"**{L['released']}:** {rel.get('release_date', '?')} · "
            f"**{L['verdict']}:** {vword}"
        )
        lines.append("")

        lines.append(f"| {L['signal']} | {L['before']} | {L['after']} | Δ |")
        lines.append("|---|---|---|---|")
        lines.append(
            f"| {L['avg_rating']} | {_fmt(sig.get('rating_before'))} | "
            f"{_fmt(sig.get('rating_after'))} | {_signed(sig.get('rating_delta'))} |"
        )
        lines.append(
            f"| {L['reviews_day']} | {_fmt(sig.get('velocity_before_per_day'))} | "
            f"{_fmt(sig.get('velocity_after_per_day'))} | "
            f"{_signed(sig.get('velocity_delta_per_day'))} |"
        )
        neg_delta = sig.get("negative_share_delta_pp")
        neg_delta_str = f"{neg_delta:+.0f}pp" if neg_delta is not None else "n/a"
        lines.append(
            f"| {L['neg_share']} | {_fmt(sig.get('negative_share_before'), '%', 0)} | "
            f"{_fmt(sig.get('negative_share_after'), '%', 0)} | "
            f"{neg_delta_str} |"
        )
        lines.append(
            f"| {L['sample']} | {sig.get('reviews_before', 0)} | {sig.get('reviews_after', 0)} | |"
        )
        lines.append("")

        # Snapshot trend (works without review text, e.g. iOS).
        mrd = sig.get("metric_rating_delta")
        if mrd is not None:
            base = sig.get("snapshot_baseline_date", "?")
            new_r = sig.get("new_ratings_since_baseline")
            extra = f", {new_r:+,} {L['new_ratings']}" if isinstance(new_r, int) else ""
            lines.append(
                f"**{L['snapshot_trend']}** ({L['since']} {base}): {L['overall_rating']} "
                f"{_signed(mrd)}{extra}."
            )
            lines.append("")
        elif sig.get("review_source") is None and sig.get("overall_rating") is not None:
            lines.append(
                f"**{L['overall_rating_cap']}:** {_fmt(sig.get('overall_rating'))} "
                f"({L['baseline_seeded']})."
            )
            lines.append("")

        issues = result.get("top_issues", [])
        if issues:
            lines.append(f"### {L['top_complaints']}")
            for it in issues:
                lines.append(f"- **{it.get('category', '?')}** ({it.get('count', 0)})")
                for ex in it.get("examples", [])[:2]:
                    lines.append(f"  - _{ex}_")
            lines.append("")

        notes = result.get("notes", [])
        if notes:
            lines.append(f"### {L['notes']}")
            for n in notes:
                lines.append(f"- {n}")
            lines.append("")

        if result.get("summary"):
            lines.append(f"### {L['summary']}")
            lines.append(result["summary"])

        return "\n".join(lines)

    # ---- sheet UC1: store metadata ----
    def _render_meta_single(self, r: dict) -> str:
        vi = r.get("lang", "en") == "vi"
        m, rk, h = r.get("metadata", {}), r.get("ranking", {}), r.get("history", {})
        L = {
            "title": "Metadata cửa hàng" if vi else "Store metadata",
            "cat": "Danh mục" if vi else "Category", "price": "Giá" if vi else "Price",
            "rel": "Phát hành" if vi else "Released", "rating": "Rating tổng" if vi else "Overall rating",
            "since": "từ" if vi else "since", "shots": "ảnh" if vi else "screenshots",
            "newver": "version mới" if vi else "new version",
            "notes": "Ghi chú" if vi else "Notes", "summary": "Tóm tắt" if vi else "Summary",
        }
        lines = [f"## 📦 {L['title']} — {m.get('name', '?')} ({m.get('store', '')})", ""]
        lines.append(
            f"**{L['cat']}:** {m.get('category') or 'n/a'} · **{L['price']}:** {m.get('price') or 'n/a'} · "
            f"**Version:** `{m.get('version') or '?'}` · **{L['rel']}:** {m.get('release_date') or '?'}"
        )
        cnt = m.get("rating_count")
        cnt_str = f" ({cnt:,} ratings)" if isinstance(cnt, int) else ""
        lines.append(f"**{L['rating']}:** {_fmt(m.get('avg_rating'))}{cnt_str}")
        if rk.get("rank"):
            lines.append(f"**Rank:** {rk.get('chart')} #{rk['rank']} ({rk.get('country')})")
        bits = []
        if h.get("rating_delta") is not None:
            bits.append(f"rating {_signed(h['rating_delta'], 3)}")
        if h.get("rank_delta") is not None:
            bits.append(f"rank {h['rank_delta']:+d}")
        if h.get("version_changed"):
            bits.append(L["newver"])
        if bits:
            lines.append(f"**Δ {L['since']} {h.get('baseline_date')}:** " + ", ".join(bits))
        if m.get("screenshot_count"):
            lines += ["", f"_{m['screenshot_count']} {L['shots']}_"]
        if r.get("notes"):
            lines += ["", f"### {L['notes']}"] + [f"- {n}" for n in r["notes"]]
        if r.get("summary"):
            lines += ["", f"### {L['summary']}", r["summary"]]
        return "\n".join(lines)

    # ---- sheet UC2: reviews & sentiment ----
    def _render_reviews_single(self, r: dict) -> str:
        vi = r.get("lang", "en") == "vi"
        app, w, t = r.get("app", {}), r.get("window", {}), r.get("totals", {})
        s, star, themes = r.get("sentiment", {}), r.get("star_distribution", {}), r.get("themes", {})
        L = {
            "title": "Review & sentiment" if vi else "Reviews & sentiment",
            "period": "Khoảng" if vi else "Window", "n": "Số review" if vi else "Reviews",
            "lang": "Ngôn ngữ" if vi else "Languages", "trend": "Xu hướng tuần" if vi else "Weekly trend",
            "praise": "👍 Khen" if vi else "👍 Praise", "comp": "👎 Phàn nàn / bug" if vi else "👎 Complaints / bugs",
            "notes": "Ghi chú" if vi else "Notes", "summary": "Tóm tắt" if vi else "Summary",
            "neg": "tiêu cực" if vi else "neg",
        }
        lines = [f"## 💬 {L['title']} — {app.get('name', '?')} ({app.get('store', '')})", ""]
        lines.append(
            f"**{L['period']}:** {w.get('from')} → {w.get('to')} · "
            f"**{L['n']}:** {t.get('reviews', 0)} · avg {_fmt(r.get('avg_rating'))}"
        )
        lines.append(
            f"**Sentiment:** 🟢 {s.get('positive', {}).get('pct', 0)}% · "
            f"⚪ {s.get('neutral', {}).get('pct', 0)}% · 🔴 {s.get('negative', {}).get('pct', 0)}%"
        )
        lines += ["", "| ★ | # | % |", "|---|---|---|"]
        for st in ("5", "4", "3", "2", "1"):
            d = star.get(st, {})
            lines.append(f"| {st}★ | {d.get('count', 0)} | {d.get('pct', 0)}% |")
        ld = r.get("language_distribution", {})
        if ld:
            lines += ["", f"**{L['lang']}:** " + ", ".join(f"{k} {v['pct']}%" for k, v in ld.items())]
        wt = r.get("weekly_trend", [])
        if wt:
            lines += ["", f"**{L['trend']}:**"]
            for row in wt[-6:]:
                lines.append(
                    f"- {row['week']}: {row['volume']} review · avg {_fmt(row.get('avg_rating'))} · "
                    f"{row.get('negative_pct', 0)}% {L['neg']}"
                )
        for key, label in (("praise", L["praise"]), ("complaints", L["comp"])):
            items = themes.get(key, [])
            if items:
                lines += ["", f"### {label}"]
                for it in items:
                    lines.append(f"- **{it.get('theme', '?')}** ({it.get('count', 0)})")
                    for ex in it.get("examples", [])[:2]:
                        lines.append(f"  - _{ex}_")
        if r.get("notes"):
            lines += ["", f"### {L['notes']}"] + [f"- {n}" for n in r["notes"]]
        if r.get("summary"):
            lines += ["", f"### {L['summary']}", r["summary"]]
        return "\n".join(lines)

    _VERDICT_LABEL = {
        "supported": "🟢 SUPPORTED",
        "partially_supported": "🟡 PARTIALLY SUPPORTED",
        "refuted": "🔴 REFUTED",
        "inconclusive": "⚪ INCONCLUSIVE",
    }

    _HC_VERDICT = {
        "en": {"supported": "🟢 SUPPORTED", "partially_supported": "🟡 PARTIALLY SUPPORTED",
               "refuted": "🔴 REFUTED", "inconclusive": "⚪ INCONCLUSIVE"},
        "vi": {"supported": "🟢 ĐÚNG", "partially_supported": "🟡 ĐÚNG MỘT PHẦN",
               "refuted": "🔴 SAI", "inconclusive": "⚪ CHƯA KẾT LUẬN"},
    }
    _HC_LABELS = {
        "en": {"conf": "confidence", "claim": "Claim", "for": "✅ Evidence for",
               "against": "⚠️ Evidence against / caveats", "sh": "Sub-hypotheses tested",
               "caveats": "📌 Caveats", "confirm": "🔬 What would confirm it", "notes": "ℹ️ Notes",
               "nec": " *(necessary)*", "of": "of", "need": "More information needed."},
        "vi": {"conf": "độ tin cậy", "claim": "Giả thuyết", "for": "✅ Bằng chứng ủng hộ",
               "against": "⚠️ Bằng chứng phản bác / lưu ý", "sh": "Giả thuyết con đã kiểm",
               "caveats": "📌 Lưu ý", "confirm": "🔬 Cần gì để khẳng định", "notes": "ℹ️ Ghi chú",
               "nec": " *(điều kiện cần)*", "of": "của", "need": "Cần thêm thông tin."},
    }

    def _render_hypothesis(self, result: dict) -> str:
        lang = result.get("lang", "en")
        L = self._HC_LABELS.get(lang, self._HC_LABELS["en"])
        # Multi-turn: still gathering context.
        if result.get("status") == "need_context":
            return f"❓ {result.get('question', L['need'])}"

        verdict = result.get("verdict", "inconclusive")
        label = self._HC_VERDICT.get(lang, self._HC_VERDICT["en"]).get(verdict, verdict.upper())
        app = result.get("app", {})
        build = result.get("build", {})
        claim = result.get("claim", {})

        lines: list[str] = []
        lines.append(f"## {label} · {L['conf']}: {result.get('confidence', 'low')}")
        lines.append("")
        lines.append(
            f"**{L['claim']}:** {claim.get('cause', '?')} → {claim.get('direction', '?')} "
            f"{claim.get('metric', '?')} {L['of']} **{app.get('name', '?')}** "
            f"(build `{build.get('version', '?')}`, {build.get('release_date', '?')})"
        )
        lines.append("")

        def bullets(title, items):
            if items:
                lines.append(f"### {title}")
                for it in items:
                    lines.append(f"- {it}")
                lines.append("")

        bullets(L["for"], result.get("evidence_for", []))
        bullets(L["against"], result.get("evidence_against", []))

        shs = result.get("sub_hypotheses", [])
        if shs:
            lines.append(f"### {L['sh']}")
            icon = {"supported": "✅", "refuted": "❌", "measured": "📊",
                    "inconclusive": "❔", "untestable": "🚫"}
            for s in shs:
                star = L["nec"] if s.get("necessary") else ""
                lines.append(
                    f"- {icon.get(s.get('status'), '•')} **{s.get('id')}**{star}: "
                    f"{s.get('statement')} — _{s.get('detail')}_"
                )
            lines.append("")

        bullets(L["caveats"], result.get("caveats", []))
        bullets(L["confirm"], result.get("what_would_confirm", []))
        bullets(L["notes"], result.get("notes", []))
        return "\n".join(lines)
