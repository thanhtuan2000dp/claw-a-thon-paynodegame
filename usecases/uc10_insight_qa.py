"""Sheet UC10 — Insight & recommendation (NL Q&A).

The agentic capstone: answer an open-ended PM question by PLANNING which analyses
to run (the other use cases), executing up to two of them, and SYNTHESISING a
direct answer + prioritised action items that cite the analyses. Orchestration
over the crawl-backed use cases, not a single fixed report.

Plannable analyses: uc1_store_metadata, uc2_reviews_sentiment, uc6_version_impact,
uc7_competitive_comparison, uc8_competitor_weakness. This use case and
hypothesis_check are excluded from the plan (avoid recursion / multi-turn).
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from core.lang import detect_lang, lang_name
from usecases.base import UseCase

_PLANNABLE = (
    "uc1_store_metadata", "uc2_reviews_sentiment", "uc6_version_impact",
    "uc7_competitive_comparison", "uc8_competitor_weakness",
)
_MAX_ANALYSES = 2


class InsightQAUseCase(UseCase):
    name = "uc10_insight_qa"
    description = (
        "Answer an OPEN-ENDED PM question that needs synthesis or a recommendation — "
        "'nên cải thiện gì', 'làm sao cạnh tranh tốt hơn', 'tổng hợp tình hình', "
        "'insight / khuyến nghị / action items', or a question spanning several aspects. "
        "Plans and runs the right analyses, then synthesises a cited answer with "
        "prioritised actions. NOT for a single focused metric / review / comparison "
        "(use the specific use case) or a causal hypothesis (hypothesis_check)."
    )
    input_schema = {
        "question": "the PM's natural-language question",
        "app": "app name/id if known (else inferred from the question)",
        "store": "ios | android | both",
        "country": "two-letter store country",
    }

    def run(self, params: dict, deps, context=None) -> dict:
        question = (params.get("question") or params.get("message")
                    or params.get("statement") or "").strip()
        if not question:
            return {"use_case": self.name, "error": "missing 'question'"}
        lang = (params.get("lang") or detect_lang(question)).lower()
        notes: list[str] = []

        from core.registry import discover_use_cases
        registry = {n: cls() for n, cls in discover_use_cases().items() if n in _PLANNABLE}
        if not registry:
            return {"use_case": self.name, "error": "no analyses available to plan"}

        plan = self._plan(question, registry, params, deps, notes, lang)
        if not plan:
            return {"use_case": self.name, "error": "could not plan analyses for the question",
                    "notes": notes}

        def run_one(step: dict):
            uc = registry.get(step["action"])
            if uc is None:
                return None
            p = dict(step.get("params") or {})
            p.setdefault("lang", lang)
            if params.get("app") and not p.get("app"):
                p["app"] = params["app"]
            if params.get("country"):
                p.setdefault("country", params["country"])
            try:
                return {"action": step["action"], "result": uc.run(p, deps, context)}
            except Exception as exc:  # noqa: BLE001 - one analysis failing must not sink the answer
                return {"action": step["action"], "error": str(exc)}

        with ThreadPoolExecutor(max_workers=_MAX_ANALYSES) as ex:
            ran = [r for r in ex.map(run_one, plan[:_MAX_ANALYSES]) if r]
        for r in ran:
            if r.get("error"):
                notes.append(f"{r['action']} failed: {r['error']}")

        synthesis = self._synthesise(question, ran, deps, notes, lang)
        return {
            "use_case": self.name,
            "lang": lang,
            "question": question,
            "analyses_run": [r["action"] for r in ran if r.get("result")],
            "answer": synthesis["answer"],
            "action_items": synthesis["action_items"],
            "notes": notes,
            "summary": (synthesis["answer"] or "")[:300] or None,
        }

    # ------------------------------------------------------------------
    def _plan(self, question, registry, params, deps, notes, lang) -> list[dict]:
        catalog = "\n".join(f"- {n}: {uc.description}" for n, uc in registry.items())
        hint = f' The question is about the app: "{params["app"]}".' if params.get("app") else ""
        prompt = (
            "You are a planning agent for an app-intelligence assistant. Choose the FEWEST "
            f"analyses (max {_MAX_ANALYSES}) that together answer the PM question, and extract "
            "parameters for each.\n"
            f"Analyses:\n{catalog}\n\n"
            f'PM question: "{question}".{hint}\n\n'
            'Return ONLY JSON: {"plan": [{"action": "<one of the analysis names>", '
            '"params": {"app": "<app name or id>", "store": "ios|android|both"}}]}. '
            "Every action's params MUST include the app the question is about."
        )
        try:
            data = deps.llm.complete_json(prompt)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Planning skipped (LLM unavailable: {exc}).")
            return []
        plan = data.get("plan") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        out = []
        for s in plan or []:
            if isinstance(s, dict) and s.get("action") in registry:
                out.append({"action": s["action"], "params": s.get("params") or {}})
        return out[:_MAX_ANALYSES]

    def _digest(self, result: dict) -> dict:
        """Compact, synthesis-friendly view of a use-case result (drop big arrays)."""
        if not isinstance(result, dict):
            return {}
        keep = ("summary", "verdict", "leaders", "opportunities", "sentiment",
                "top_issues", "themes", "ranking", "comparison")
        d = {k: result[k] for k in keep if k in result}
        if result.get("mode") == "cross_platform":
            d["platforms"] = {s: p.get("summary") for s, p in result.get("platforms", {}).items()}
        return d

    def _synthesise(self, question, ran, deps, notes, lang) -> dict:
        digests = {r["action"]: self._digest(r["result"]) for r in ran if r.get("result")}
        if not digests:
            notes.append("No analysis produced a result to synthesise.")
            return {"answer": "", "action_items": []}
        prompt = (
            "You are a product-strategy advisor. Using ONLY the analysis results below, "
            f'answer the PM question and give prioritised action items. Question: "{question}".\n\n'
            f"Analysis results (JSON):\n{json.dumps(digests, ensure_ascii=False)[:6000]}\n\n"
            f"Write in {lang_name(lang)}. Return ONLY JSON: "
            '{"answer": "direct answer in 2-4 sentences", "action_items": '
            '[{"action": "what to do", "rationale": "why — cite the analysis", "priority": "high|medium|low"}]}.'
        )
        try:
            data = deps.llm.complete_json(prompt)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Synthesis skipped (LLM unavailable: {exc}); raw summaries returned.")
            return {"answer": " ".join((d.get("summary") or "") for d in digests.values()).strip(),
                    "action_items": []}
        data = data if isinstance(data, dict) else {}
        items = [
            {"action": it.get("action"), "rationale": it.get("rationale"), "priority": it.get("priority")}
            for it in (data.get("action_items") or [])
            if isinstance(it, dict) and it.get("action")
        ]
        return {"answer": data.get("answer") or "", "action_items": items[:6]}
