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
        if uc == "uc3_version_changelog":
            return self._render_cross(result, self._render_uc3_single, "🗒️", "Version changelog", "Lịch sử phiên bản") \
                if result.get("mode") == "cross_platform" else self._render_uc3_single(result)
        if uc == "uc7_competitive_comparison":
            return self._render_uc7(result)
        if uc == "uc8_competitor_weakness":
            return self._render_uc8(result)
        if uc == "uc10_insight_qa":
            return self._render_uc10(result)
        if uc == "uc4_kpi_dashboard":
            return self._render_cross(result, self._render_uc4_single, "📈", "KPI dashboard", "Bảng KPI") \
                if result.get("mode") == "cross_platform" else self._render_uc4_single(result)
        if uc == "uc9_trend_alert":
            return self._render_cross(result, self._render_uc9_single, "🚨", "Trend alerts", "Cảnh báo biến động") \
                if result.get("mode") == "cross_platform" else self._render_uc9_single(result)
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

    # ---- sheet UC10: insight & NL Q&A ----
    def _render_uc10(self, r: dict) -> str:
        vi = r.get("lang", "en") == "vi"
        L = {
            "title": "Tư vấn & khuyến nghị" if vi else "Insight & recommendations",
            "q": "Câu hỏi" if vi else "Question", "used": "Đã chạy" if vi else "Analyses run",
            "actions": "✅ Hành động đề xuất" if vi else "✅ Recommended actions",
            "notes": "Ghi chú" if vi else "Notes",
        }
        lines = [f"## 🧭 {L['title']}", "", f"**{L['q']}:** {r.get('question', '?')}"]
        used = r.get("analyses_run", [])
        if used:
            lines.append(f"_{L['used']}: {', '.join(used)}_")
        if r.get("answer"):
            lines += ["", r["answer"]]
        items = r.get("action_items", [])
        if items:
            lines += ["", f"### {L['actions']}"]
            for it in items:
                pri = (it.get("priority") or "").lower()
                tag = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(pri, "•")
                lines.append(f"- {tag} **{it.get('action', '?')}** — {it.get('rationale') or ''}")
        if r.get("notes"):
            real = [n for n in r["notes"] if n]
            if real:
                lines += ["", f"### {L['notes']}"] + [f"- {n}" for n in real]
        return "\n".join(lines)

    # ---- sheet UC4: KPI dashboard ----
    def _render_uc4_single(self, r: dict) -> str:
        vi = r.get("lang", "en") == "vi"
        app, k, d = r.get("app", {}), r.get("kpis", {}), r.get("deltas", {})
        L = {"title": "Bảng KPI" if vi else "KPI dashboard", "n": "Lượt rating" if vi else "Ratings",
             "since": "từ" if vi else "since", "date": "Ngày" if vi else "Date",
             "notes": "Ghi chú" if vi else "Notes", "summary": "Tóm tắt" if vi else "Summary"}
        cnt = k.get("ratings_count")
        cnt_s = f"{cnt:,}" if isinstance(cnt, int) else "n/a"
        lines = [f"## 📈 {L['title']} — {app.get('name', '?')} ({app.get('store', '')})", ""]
        lines.append(f"**Rating:** {_fmt(k.get('rating'))} · **Rank:** {k.get('rank_chart') or '?'} "
                     f"#{k.get('rank') or 'n/a'} · **{L['n']}:** {cnt_s} · **Version:** `{k.get('version') or '?'}`")
        if d.get("since"):
            bits = []
            if d.get("rating") is not None:
                bits.append(f"rating {_signed(d['rating'], 3)}")
            if d.get("rank") is not None:
                bits.append(f"rank {d['rank']:+d}")
            if isinstance(d.get("ratings_count"), int):
                bits.append(f"{d['ratings_count']:+,} ratings")
            if bits:
                lines.append(f"**Δ {L['since']} {d['since']}:** " + ", ".join(bits))
        trend = r.get("trend", [])
        if len(trend) > 1:
            lines += ["", f"| {L['date']} | Rating | Rank | {L['n']} |", "|---|---|---|---|"]
            for row in trend[-8:]:
                rc = row.get("ratings_count")
                lines.append(f"| {row['date']} | {_fmt(row.get('rating'))} | {row.get('rank') or 'n/a'} | "
                             f"{rc:,} |" if isinstance(rc, int) else
                             f"| {row['date']} | {_fmt(row.get('rating'))} | {row.get('rank') or 'n/a'} | n/a |")
        if r.get("notes"):
            lines += ["", f"### {L['notes']}"] + [f"- {n}" for n in r["notes"]]
        if r.get("summary"):
            lines += ["", f"### {L['summary']}", r["summary"]]
        return "\n".join(lines)

    # ---- sheet UC9: trend & anomaly alert ----
    def _render_uc9_single(self, r: dict) -> str:
        vi = r.get("lang", "en") == "vi"
        app, cur = r.get("app", {}), r.get("current", {})
        L = {"title": "Cảnh báo biến động" if vi else "Trend alerts",
             "now": "Hiện tại" if vi else "Now", "alerts": "🚨 Cảnh báo" if vi else "🚨 Alerts",
             "since": "từ" if vi else "since"}
        lines = [f"## 🚨 {L['title']} — {app.get('name', '?')} ({app.get('store', '')})", ""]
        lines.append(f"**{L['now']}:** rating {_fmt(cur.get('rating'))} · "
                     f"rank {cur.get('rank_chart') or '?'} #{cur.get('rank') or 'n/a'} · v`{cur.get('version') or '?'}`")
        if r.get("status") == "baseline_seeded":
            lines += ["", f"_{r.get('summary', '')}_"]
            return "\n".join(lines)
        alerts = r.get("alerts", [])
        icon = {"high": "🔴", "medium": "🟡", "info": "🔵"}
        if alerts:
            lines += ["", f"### {L['alerts']} ({L['since']} {r.get('baseline_date')})"]
            lines += [f"- {icon.get(a.get('severity'), '•')} {a.get('message')}" for a in alerts]
        else:
            lines += ["", f"✅ {r.get('summary', '')}"]
        return "\n".join(lines)

    # ---- sheet UC3: version changelog timeline ----
    def _render_uc3_single(self, r: dict) -> str:
        vi = r.get("lang", "en") == "vi"
        app = r.get("app", {})
        L = {
            "title": "Lịch sử phiên bản" if vi else "Version changelog",
            "current": "Hiện tại" if vi else "Current",
            "released": "phát hành" if vi else "released",
            "no_notes": "_(store không kèm release notes)_" if vi else "_(no release notes on the store)_",
            "highlights": "✨ Điểm nổi bật qua các bản" if vi else "✨ Highlights across versions",
            "versions": "📜 Các phiên bản (mới nhất trước)" if vi else "📜 Versions (newest first)",
            "notes": "Ghi chú" if vi else "Notes", "summary": "Tóm tắt" if vi else "Summary",
        }
        lines = [f"## 🗒️ {L['title']} — {app.get('name', '?')} ({app.get('store', '')})", ""]
        lines.append(f"**{L['current']}:** `v{r.get('current_version') or '?'}`")
        versions = r.get("versions", [])
        if versions:
            lines += ["", f"### {L['versions']}"]
            for v in versions:
                rel = v.get("release_date") or v.get("first_seen")
                rel = str(rel).split("T")[0] if rel else "?"
                lines.append(f"- **v{v.get('version', '?')}** · {L['released']} {rel}")
                notes = v.get("release_notes")
                lines.append(f"  - _{notes}_" if notes else f"  - {L['no_notes']}")
        hl = r.get("highlights", [])
        if hl:
            lines += ["", f"### {L['highlights']}"] + [f"- {h}" for h in hl]
        if r.get("notes"):
            real = [n for n in r["notes"] if n]
            if real:
                lines += ["", f"### {L['notes']}"] + [f"- {n}" for n in real]
        if r.get("summary"):
            lines += ["", f"### {L['summary']}", r["summary"]]
        return "\n".join(lines)

    # ---- sheet UC7: competitive comparison ----
    def _render_uc7(self, r: dict) -> str:
        vi = r.get("lang", "en") == "vi"
        app = r.get("app", {})
        L = {
            "title": "So sánh cạnh tranh" if vi else "Competitive comparison",
            "appc": "App" if vi else "App", "rank": "Rank", "rating": "Rating",
            "n": "Lượt rating" if vi else "Ratings", "price": "Giá" if vi else "Price",
            "leaders": "Dẫn đầu" if vi else "Leaders", "scale": "quy mô" if vi else "scale",
            "insights": "📊 Định vị" if vi else "📊 Positioning", "notes": "Ghi chú" if vi else "Notes",
            "summary": "Tóm tắt" if vi else "Summary",
        }
        cat = app.get("category")
        lines = [f"## ⚔️ {L['title']} — {app.get('name', '?')}" + (f" · {cat}" if cat else ""), ""]
        lines += [f"| {L['appc']} | {L['rank']} | {L['rating']} | {L['n']} | {L['price']} | Version |",
                  "|---|---|---|---|---|---|"]
        for row in r.get("comparison", []):
            mark = "⭐ " if row.get("is_you") else ""
            cnt = row.get("ratings_count")
            cnt_s = f"{cnt:,}" if isinstance(cnt, int) else "n/a"
            lines.append(
                f"| {mark}{row.get('name', '?')} | {row.get('rank') or 'n/a'} | "
                f"{_fmt(row.get('rating'))} | {cnt_s} | {row.get('price') or 'n/a'} | "
                f"{row.get('version') or 'n/a'} |"
            )
        ld = r.get("leaders", {})
        lines += ["", f"**{L['leaders']}:** rating → {ld.get('rating') or 'n/a'} · "
                  f"rank → {ld.get('rank') or 'n/a'} · {L['scale']} → {ld.get('ratings_count') or 'n/a'}"]
        pos = r.get("positioning", [])
        if pos:
            lines += ["", f"### {L['insights']}"] + [f"- {p}" for p in pos]
        if r.get("notes"):
            real = [n for n in r["notes"] if n]
            if real:
                lines += ["", f"### {L['notes']}"] + [f"- {n}" for n in real]
        if r.get("summary"):
            lines += ["", f"### {L['summary']}", r["summary"]]
        return "\n".join(lines)

    # ---- sheet UC8: competitor weakness mining ----
    def _render_uc8(self, r: dict) -> str:
        vi = r.get("lang", "en") == "vi"
        app, w = r.get("app", {}), r.get("window", {})
        L = {
            "title": "Điểm yếu đối thủ → cơ hội" if vi else "Competitor weaknesses → opportunities",
            "period": "Khoảng" if vi else "Window", "rivals": "Đối thủ" if vi else "Rivals",
            "opps": "🎯 Cơ hội (ưu tiên)" if vi else "🎯 Opportunities (prioritised)",
            "notes": "Ghi chú" if vi else "Notes", "summary": "Tóm tắt" if vi else "Summary",
            "neg": "tiêu cực" if vi else "neg",
        }
        cat = app.get("category")
        head = f"{app.get('name', '?')}" + (f" · {cat}" if cat else f" ({app.get('store', '')})")
        lines = [f"## 🎯 {L['title']} — {head}", ""]
        lines.append(f"**{L['period']}:** {w.get('from')} → {w.get('to')}")
        rivals = r.get("competitors", [])
        if rivals:
            lines.append(
                f"**{L['rivals']}:** "
                + " · ".join(f"{c['name']} ({c.get('negative_reviews', 0)} {L['neg']})" for c in rivals)
            )
        opps = r.get("opportunities", [])
        if opps:
            lines += ["", f"### {L['opps']}"]
            for i, o in enumerate(opps, 1):
                cat_tag = f" _{o.get('category')}_" if o.get("category") else ""
                lines.append(f"{i}. **{o.get('theme', '?')}**{cat_tag} ({o.get('count', 0)}) — {o.get('opportunity') or ''}")
                aff = o.get("competitors") or []
                if aff:
                    lines.append(f"   ↳ {', '.join(aff)}")
                for ex in o.get("examples", [])[:2]:
                    lines.append(f"   - _{ex}_")
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
