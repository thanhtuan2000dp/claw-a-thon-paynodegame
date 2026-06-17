"""Hypothesis Checker — diagnostic, multi-turn.

Takes an executive's informal claim ("feature X raised revenue of app Y in build
Z"), asks clarifying questions across turns until it has enough context, then
tests the claim against data via the matching product-analytics framework and
returns a calibrated verdict with evidence for/against, confounders, and caveats.

Intellectual honesty is the point: signals needing data we cannot get (revenue/
downloads on a metadata-only Sensor Tower token) are marked UNTESTABLE and cap the
verdict — the agent never fabricates a confident answer.

Multi-turn state lives in deps.conversation (swappable backend). The claim is
re-derived from the full conversation each turn, so state is robust.
"""

from __future__ import annotations

import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from connectors.base import CAP_DOWNLOADS, CAP_METADATA, CAP_REVIEWS, CAP_SEARCH, ConnectorError, Review
from core.lang import detect_lang, market_for
from frameworks.base import (
    SIG_DOWNLOAD_DELTA,
    SIG_FEATURE_MENTION,
    SIG_METRIC_RATING,
    SIG_NEG_SHARE,
    SIG_RATING_DELTA,
    SIG_REVENUE_DELTA,
    SIG_REVIEW_VELOCITY,
    SIG_TIMING,
    framework_for,
)
from usecases.base import UseCase

REQUIRED_SLOTS = ["entity", "metric", "direction", "cause", "build", "store"]


def _ensemble_models() -> list[str | None]:
    """Models to poll for the verdict. ``HYPOTHESIS_ENSEMBLE_MODELS`` is an
    optional comma-separated list of model paths (e.g.
    ``qwen/qwen3-5-27b,minimax/minimax-m2.5,openai/gpt-oss-20b``). Unset = a
    single call on the default LLM_MODEL — i.e. exactly the prior behaviour."""
    raw = os.environ.get("HYPOTHESIS_ENSEMBLE_MODELS", "").strip()
    if not raw:
        return [None]
    models = [m.strip() for m in raw.split(",") if m.strip()]
    return models or [None]


def _gate_verdict(verdict: str, necessary: dict | None) -> str:
    """Enforce the intellectual-honesty GATE in code, not just in the prompt:
    an untestable necessary condition caps the verdict at 'inconclusive'; a
    refuted one forces 'refuted'. Guarantees the invariant even if a model
    ignores the prompt instruction."""
    if necessary:
        if necessary["status"] == "refuted":
            return "refuted"
        if necessary["status"] == "untestable" and verdict in ("supported", "partially_supported"):
            return "inconclusive"
    return verdict


def _naive(dt):
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _looks_like_id(app: str, store: str) -> bool:
    import re

    if store == "ios":
        return app.isdigit()
    return bool(re.fullmatch(r"[a-zA-Z][\w.]+\.[\w.]+", app))


class HypothesisCheckUseCase(UseCase):
    name = "hypothesis_check"
    description = (
        "Test a CAUSAL claim / hypothesis — when the user proposes or suspects a CAUSE "
        "for a metric or outcome ('rating giảm do bản cập nhật', 'feature X raised revenue', "
        "'X gây Y', or a tag-question guessing a cause like '… à?'/'… đúng không?'). Gathers "
        "evidence for and against and returns a verdict with confidence. Multi-turn — asks "
        "for missing context. NOT for a plain data lookup or 'what do users say' (that is "
        "uc2_reviews_sentiment) or 'how did the latest update do' (that is uc6_version_impact)."
    )
    input_schema = {
        "statement": "the informal claim to test (first turn)",
        "message": "an answer to a clarifying question (subsequent turns)",
        "session_id": "conversation id (auto from request context if omitted)",
    }

    # ------------------------------------------------------------------
    def run(self, params: dict, deps, context=None) -> dict:
        session_id = (
            getattr(context, "session_id", None)
            or params.get("session_id")
            or "default"
        )
        msg = (params.get("statement") or params.get("message") or "").strip()
        store = deps.conversation

        if msg:
            store.append(session_id, "user", msg)
        history = store.history(session_id)

        # Detect language from full conversation history, not just the current
        # message. The router sets params["lang"] from one message at a time, so
        # an all-ASCII turn ("android", "ios", "do app loi") would flip the
        # language mid-session. Scanning all user turns is more reliable.
        user_texts = [t["content"] for t in history if t.get("role") == "user"] or [msg]
        lang = detect_lang(*user_texts).lower()

        if not history:
            q = ('Bạn muốn kiểm chứng giả thuyết gì? '
                 'Ví dụ: "tính năng X làm tăng revenue của app Y ở build mới nhất".')
            return self._ask(store, session_id, q, {}, [])

        parsed = self._parse(history, deps)
        claim = parsed.get("claim", {}) if isinstance(parsed, dict) else {}
        missing = [m for m in (parsed.get("missing") or []) if m in REQUIRED_SLOTS]

        if missing:
            q = parsed.get("next_question") or (
                "Cần thêm thông tin: " + ", ".join(missing) + "."
            )
            return self._ask(store, session_id, q, claim, missing)

        result = self._analyze(claim, deps, lang)
        store.clear(session_id)
        result.update(use_case=self.name, status="complete", session_id=session_id, claim=claim, lang=lang)
        return result

    def _ask(self, store, session_id, question, claim, missing) -> dict:
        store.append(session_id, "assistant", question)
        return {
            "use_case": self.name,
            "status": "need_context",
            "question": question,
            "missing": missing,
            "claim_so_far": claim,
            "session_id": session_id,
        }

    # ------------------------------------------------------------------
    def _parse(self, history: list[dict], deps) -> dict:
        convo = "\n".join(f"{t['role']}: {t['content']}" for t in history)
        prompt = (
            "You are a product-analytics assistant. From the conversation, extract a "
            "structured claim and decide what REQUIRED context is still missing to test "
            "it rigorously.\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "claim": {\n'
            '    "entity": "app name or store id (null if unknown)",\n'
            '    "metric": "revenue|rating|downloads|retention",\n'
            '    "direction": "increase|decrease",\n'
            '    "cause": "the feature/change hypothesised to drive it",\n'
            '    "build": "version string or \'latest\'",\n'
            '    "store": "ios",\n'
            '    "timeframe_days": 30,\n'
            '    "baseline": "prior_window"\n'
            "  },\n"
            '  "missing": ["names of REQUIRED slots that are still absent"],\n'
            '  "next_question": "one short clarifying question, in the user\'s language, for the most important missing slot"\n'
            "}\n\n"
            f"REQUIRED slots: {REQUIRED_SLOTS}. timeframe_days defaults to 30 and baseline to "
            "'prior_window' (these are NOT missing if absent). If the user said 'mới nhất'/'latest' "
            "for build, treat build as 'latest' (not missing). Infer metric from the wording. "
            "'store' is one of 'ios', 'android', or 'both' — use 'both' when the user clearly "
            "wants both platforms; never output combined forms like 'ios|android'.\n"
            "IMPORTANT: 'cause' must be a plain human-readable description extracted from the "
            "user's own words (e.g. 'app crash bug', 'new payment feature'). NEVER use internal "
            "system identifiers such as 'uc6_version_impact', 'uc2_reviews_sentiment', or any "
            "underscore-separated code name. If the cause is a version update with no specific "
            "feature named, use 'bản cập nhật mới' (Vietnamese) or 'new update' (English).\n\n"
            f"Conversation:\n{convo}"
        )
        try:
            data = deps.llm.complete_json(prompt)
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001 - if parsing fails, ask broadly
            return {"claim": {}, "missing": ["entity"], "next_question":
                    "Bạn có thể nêu rõ app, build, và bạn nghĩ yếu tố nào tác động tới chỉ số nào không?"}

    # ------------------------------------------------------------------
    def _analyze(self, claim: dict, deps, lang: str = "en") -> dict:
        # hypothesis_check analyses ONE build on ONE store. Normalise whatever the
        # parser produced ("both", "ios|android", empty, garbage) into the store(s)
        # to try, best-first, and resolve on the first where the app exists.
        raw_store = (claim.get("store") or deps.config.get("default_store", "ios")).lower()
        if raw_store in ("both", "all", "cross", "cross_platform") or (
            "ios" in raw_store and "android" in raw_store
        ):
            candidates = ["ios", "android"]
        else:
            candidates = [s for s in ("ios", "android") if s in raw_store] or ["ios"]
        store = candidates[0]
        country, _ = market_for(lang)
        metric = (claim.get("metric") or "rating").lower()
        notes: list[str] = []

        def _cannot(reason: str) -> dict:
            return {
                "verdict": "inconclusive",
                "confidence": "low",
                "evidence_for": [],
                "evidence_against": [],
                "caveats": [reason],
                "what_would_confirm": [
                    "Pass the exact store id (iOS trackId / Android package) for precise resolution."
                ],
                "app": {"name": claim.get("entity"), "store": store},
            }

        app_ref = None
        for s in candidates:
            app_ref = self._resolve(claim.get("entity") or "", s, deps, country, lang)
            if app_ref and app_ref.app_id:
                store = s
                break
        if app_ref is None or not app_ref.app_id:
            return _cannot(f"Could not resolve app '{claim.get('entity')}' on {'/'.join(candidates)}.")
        if len(candidates) > 1:
            notes.append(
                f"Tested on {store} (one store per run); ask again for the other store to compare."
                if lang == "en" else
                f"Kiểm chứng trên {store} (mỗi lần một store); hỏi lại cho store còn lại để so sánh."
            )

        meta_conn = deps.connector_for(CAP_METADATA, store)
        try:
            meta = meta_conn.get_metadata(app_ref.app_id, store, country=country, lang=lang)
        except ConnectorError as exc:
            return _cannot(f"Could not fetch metadata for '{claim.get('entity')}' ({exc}).")
        release_dt = _naive(meta.current_version_release_date)
        if claim.get("build") not in (None, "", "latest") and meta.version and claim["build"] not in str(meta.version):
            notes.append(
                f"Free data exposes only the current version ({meta.version}); analysed "
                f"its release window as a proxy for build '{claim['build']}'."
            )

        framework = framework_for(metric)
        if framework is None:
            framework = framework_for("rating")
            notes.append(f"No framework for metric '{metric}'; used the rating framework.")
        shs = framework.sub_hypotheses(claim, lang=lang)

        signals = self._gather(claim, app_ref, meta, release_dt, store, deps, notes, country, lang)
        sh_results = self._evaluate(shs, signals, store, deps, lang=lang)
        narrative = self._narrative(claim, sh_results, signals, deps, lang)

        return {
            "app": {"app_id": meta.app_id, "name": meta.name, "store": store},
            "build": {"version": meta.version,
                      "release_date": release_dt.date().isoformat() if release_dt else None},
            "metric": metric,
            "framework": framework.metric,
            "signals": signals.get("public", {}),
            "sub_hypotheses": sh_results,
            "notes": notes + signals.get("notes", []),
            **narrative,
        }

    # ------------------------------------------------------------------
    def _resolve(self, app_query: str, store: str, deps, country=None, lang=None):
        app_query = app_query.strip()
        if not app_query:
            return None
        if _looks_like_id(app_query, store):
            from connectors.base import AppRef

            return AppRef(app_id=app_query, name=app_query, store=store)
        conn = deps.connector_for(CAP_SEARCH, store)
        if conn is None:
            return None
        try:
            hits = conn.search_app(app_query, store, country=country, lang=lang)
        except ConnectorError:
            return None
        return hits[0] if hits else None

    def _gather(self, claim, app_ref, meta, release_dt, store, deps, notes, country=None, lang=None) -> dict:
        window = int(claim.get("timeframe_days") or 30)
        cause = (claim.get("cause") or "").lower()
        before: list[Review] = []
        after: list[Review] = []
        review_source = None
        downloads_available = bool(deps.connectors_for(CAP_DOWNLOADS, store))

        if release_dt is not None:
            for conn in deps.connectors_for(CAP_REVIEWS, store):
                try:
                    now = datetime.utcnow()
                    revs = conn.get_reviews(app_ref.app_id, store, release_dt - timedelta(days=window), now, country=country, lang=lang)
                    review_source = conn.name
                    for r in revs:
                        rd = _naive(r.date)
                        if rd is None:
                            continue
                        (before if rd < release_dt else after).append(r)
                    break
                except ConnectorError as exc:
                    notes.append(f"{conn.name} reviews unavailable ({exc}).")

        def avg(xs):
            xs = [x for x in xs if x is not None]
            return round(sum(xs) / len(xs), 3) if xs else None

        def neg(rs):
            rated = [r for r in rs if r.rating is not None]
            return round(100.0 * sum(1 for r in rated if r.rating <= 2) / len(rated), 1) if rated else None

        rating_before = avg([r.rating for r in before])
        rating_after = avg([r.rating for r in after])
        rating_delta = round(rating_after - rating_before, 3) if rating_before is not None and rating_after is not None else None
        days_after = max(1, (datetime.utcnow() - release_dt).days) if release_dt else 1
        vel_before = round(len(before) / window, 2) if before else None
        vel_after = round(len(after) / days_after, 2) if after else None
        neg_before, neg_after = neg(before), neg(after)
        feature_hits = sum(1 for r in after if cause and cause in (r.content or "").lower()) if cause else 0

        # snapshot trend (no reviews needed)
        hist = deps.storage.history(meta.app_id, store)
        prior = hist[-1] if hist else None
        metric_rating_delta = None
        if prior and prior.avg_rating is not None and meta.avg_rating is not None:
            metric_rating_delta = round(meta.avg_rating - prior.avg_rating, 3)

        return {
            "raw": {
                "rating_delta": rating_delta,
                "metric_rating_delta": metric_rating_delta,
                "velocity_before": vel_before, "velocity_after": vel_after,
                "neg_before": neg_before, "neg_after": neg_after,
                "feature_hits": feature_hits, "feature_term": cause or None,
                "reviews_before": len(before), "reviews_after": len(after),
                "downloads_available": downloads_available,
                "release_dt": release_dt,
            },
            "public": {
                "review_source": review_source,
                "rating_before": rating_before, "rating_after": rating_after,
                "rating_delta": rating_delta,
                "reviews_before": len(before), "reviews_after": len(after),
                "neg_share_before": neg_before, "neg_share_after": neg_after,
                "feature_mentions_after": feature_hits,
                "metric_rating_delta": metric_rating_delta,
                "downloads_available": downloads_available,
            },
            "notes": [],
        }

    def _evaluate(self, shs, signals, store, deps, lang: str = "en") -> list[dict]:
        raw = signals["raw"]
        results = []
        for sh in shs:
            available = True
            if sh.data_need == CAP_REVIEWS:
                available = signals["public"]["review_source"] is not None
            elif sh.data_need == CAP_DOWNLOADS:
                available = raw["downloads_available"]
            status, detail = self._status_for(sh.signal, raw, available, lang=lang)
            results.append({
                "id": sh.id, "statement": sh.statement, "signal": sh.signal,
                "necessary": sh.necessary, "status": status, "detail": detail,
            })
        return results

    def _status_for(self, signal, raw, available, lang: str = "en"):
        vi = lang == "vi"
        if not available:
            return "untestable", (
                "không thể truy cập dữ liệu cần thiết (phạm vi token / store)" if vi else
                "required data not accessible (token scope / store)"
            )
        if signal in (SIG_REVENUE_DELTA, SIG_DOWNLOAD_DELTA):
            return "untestable", (
                "ước tính downloads/doanh thu cần token Sensor Tower có phạm vi phù hợp" if vi else
                "downloads/revenue estimates need a Sensor Tower token with that scope"
            )
        if signal == SIG_RATING_DELTA:
            d = raw["rating_delta"]
            if d is None:
                return "inconclusive", (
                    "không có rating trước/sau (không có review baseline trong khoảng thời gian)" if vi else
                    "no before/after review rating (no baseline reviews in window)"
                )
            return "measured", (
                f"biến động rating review {d:+.3f}" if vi else f"review rating delta {d:+.3f}"
            )
        if signal == SIG_METRIC_RATING:
            d = raw["metric_rating_delta"]
            if d is None:
                return "inconclusive", ("chưa có snapshot trước đó" if vi else "no prior snapshot")
            return "measured", (
                f"biến động rating snapshot {d:+.3f}" if vi else f"snapshot rating delta {d:+.3f}"
            )
        if signal == SIG_NEG_SHARE:
            b, a = raw["neg_before"], raw["neg_after"]
            if a is None:
                return "inconclusive", ("không có review sau khi phát hành" if vi else "no post-release reviews")
            b_str = b if b is not None else "?"
            return "measured", (
                f"tỷ lệ review tiêu cực {b_str}% → {a}%" if vi else f"negative share {b_str}% -> {a}%"
            )
        if signal == SIG_REVIEW_VELOCITY:
            bv, av = raw["velocity_before"], raw["velocity_after"]
            return "measured", (
                f"lượng review {bv} → {av}/ngày" if vi else f"velocity {bv} -> {av}/day"
            )
        if signal == SIG_FEATURE_MENTION:
            h = raw["feature_hits"]
            term = raw["feature_term"]
            if vi:
                detail = f"{h} review sau khi phát hành đề cập đến '{term}'"
            else:
                detail = f"{h} post-release reviews mention '{term}'"
            return ("supported" if h > 0 else "inconclusive"), detail
        if signal == SIG_TIMING:
            if raw["release_dt"]:
                return "measured", ("đã biết ngày phát hành" if vi else "release date known")
            return "inconclusive", ("không rõ ngày phát hành" if vi else "no release date")
        return "inconclusive", ""

    def _narrative(self, claim, sh_results, signals, deps, lang: str = "en") -> dict:
        necessary = next((r for r in sh_results if r["necessary"]), None)
        gate = ""
        if necessary:
            if necessary["status"] == "untestable":
                gate = "The NECESSARY condition is UNTESTABLE, so the verdict CANNOT be 'supported' — use 'inconclusive' at best."
            elif necessary["status"] == "refuted":
                gate = "The NECESSARY condition is REFUTED, so the verdict MUST be 'refuted'."
        prompt = (
            "You are a rigorous, skeptical product analyst. Judge the user's claim from the "
            "sub-hypothesis results and signals. Be intellectually honest: label estimates as "
            "estimates, never assert causation from correlation, and surface the strongest "
            "confounder.\n\n"
            f"CLAIM: {claim}\n"
            f"SUB-HYPOTHESIS RESULTS: {sh_results}\n"
            f"SIGNALS: {signals['public']}\n"
            f"GATE: {gate}\n\n"
            "Return ONLY JSON: {\n"
            '  "verdict": "supported|partially_supported|refuted|inconclusive",\n'
            '  "confidence": "low|medium|high",\n'
            '  "evidence_for": ["short bullet with numbers"],\n'
            '  "evidence_against": ["short bullet"],\n'
            '  "caveats": ["correlation vs causation, estimate caveats, small samples"],\n'
            '  "what_would_confirm": ["data not in public sources that would settle it"]\n'
            "}\n"
            f"Respect the GATE. Keep bullets concise. Write ALL text in "
            f"{'Vietnamese' if lang == 'vi' else 'English'}."
        )
        # Poll an ensemble of models concurrently (one call by default), then
        # majority-vote the verdict. Independent voices guard the GATE: a single
        # over-confident model can't carry a 'supported' past the panel.
        models = _ensemble_models()

        def _one(model: str | None) -> dict | None:
            try:
                data = deps.llm_for(model).complete_json(prompt)
                if isinstance(data, dict) and data.get("verdict"):
                    return data
            except Exception:  # noqa: BLE001 - a dead model just doesn't vote
                return None
            return None

        if len(models) == 1:
            results = [_one(models[0])]
        else:
            with ThreadPoolExecutor(max_workers=len(models)) as ex:
                results = list(ex.map(_one, models))
        results = [r for r in results if r]

        if results:
            # Vote on the GATE-enforced verdict, not the raw one.
            gated = [(_gate_verdict(r.get("verdict", "inconclusive"), necessary), r) for r in results]
            tally = Counter(v for v, _ in gated)
            winner, agree = tally.most_common(1)[0]
            chosen = next(r for v, r in gated if v == winner)  # narrative from a winner
            confidence = chosen.get("confidence", "low")
            caveats = list(chosen.get("caveats", []))
            if len(results) > 1:
                # A split panel can't claim high confidence.
                if agree < len(results):
                    confidence = "low" if agree * 2 <= len(results) else "medium"
                caveats.append(f"Ensemble of {len(results)} models; {agree}/{len(results)} agreed on '{winner}'.")
            return {
                "verdict": winner,
                "confidence": confidence,
                "evidence_for": chosen.get("evidence_for", []),
                "evidence_against": chosen.get("evidence_against", []),
                "caveats": caveats,
                "what_would_confirm": chosen.get("what_would_confirm", []),
            }
        # deterministic fallback if LLM unavailable
        verdict = "inconclusive"
        if necessary and necessary["status"] == "refuted":
            verdict = "refuted"
        return {
            "verdict": verdict, "confidence": "low",
            "evidence_for": [r["detail"] for r in sh_results if r["status"] in ("supported", "measured")],
            "evidence_against": [],
            "caveats": ["LLM narrative unavailable; showing raw sub-hypothesis results."],
            "what_would_confirm": [],
        }
