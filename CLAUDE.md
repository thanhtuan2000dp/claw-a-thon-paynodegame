# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**App Intelligence Agent** — a GreenNode AgentBase agent (Claw-a-thon 2026, Automation & Integration track) that turns public app-store signals into product decisions. It ships several use cases from the "AI Agent UseCases" sheet — store-metadata crawl (sheet UC1 = `uc1_store_metadata`), reviews & sentiment (sheet UC2 = `uc2_reviews_sentiment`), and a post-release health check (sheet UC6 = `uc6_version_impact`) — plus a standalone Hypothesis Checker that stress-tests an executive's claim against the data (not part of the sheet).

It is a Starlette-based HTTP service wrapped by `greennode-agentbase`: `GET /health`, `GET /` (chat UI), `POST /invocations`.

## Commands

```bash
# Setup (Python 3.10+; Docker image uses 3.12)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill LLM_* (required) and optional SENSORTOWER_AUTH_TOKEN

# Run — serves on http://0.0.0.0:8080
python main.py

# Tests (run with the venv interpreter; they self-insert the repo root on sys.path)
./venv/bin/python tests/test_uc6_version_impact.py            # synthetic asserts + live iTunes + Google Play
./venv/bin/python tests/test_uc6_version_impact.py --no-live  # offline analytics asserts only (no network/LLM)
./venv/bin/python tests/verify_uc1_store_metadata.py          # sheet UC1 metadata (live)
./venv/bin/python tests/verify_uc2_reviews_sentiment.py      # sheet UC2 reviews & sentiment (live)
./venv/bin/python tests/test_hypothesis.py      # Hypothesis Checker multi-turn run
./venv/bin/python tests/verify_sensortower.py   # probe Sensor Tower endpoints with your token (never prints the token)
```

There is no test runner config, linter, or build step — tests are plain `python` scripts with `if __name__ == "__main__"` entrypoints, not pytest. Add `--no-live` style flags inside the script when a test needs an offline mode.

### Invoking the agent

```bash
# Explicit action
curl -X POST http://127.0.0.1:8080/invocations -H "Content-Type: application/json" \
  -d '{"action": "uc6_version_impact", "params": {"app": "Spotify", "store": "ios", "country": "us"}}'

# Natural language (LLM router picks the action + extracts params)
curl -X POST http://127.0.0.1:8080/invocations -H "Content-Type: application/json" \
  -d '{"message": "check the health of Instagram'\''s latest Android update"}'
```

## Architecture

The runtime is a **thin shell over a fully decoupled core**. `main.py` is the only file that imports `greennode-agentbase`; everything in `core/`, `connectors/`, `usecases/`, `frameworks/`, `outputs/`, `storage/` is plain Python with no runtime/network-framework dependency, so all business logic is unit-testable without the platform. Do not import `greennode_agentbase` outside `main.py`.

Request flow:

```
POST /invocations → main.handler → core.router.Router.handle → UseCase.run(params, deps, context)
```

- **`core/router.py`** — dispatches `{"action", "params"}` directly, or routes `{"message": ...}` **LLM-first** (`_route_nl`): one structured call picks the action **by each use case's `description`** (the descriptions declare what each is and is NOT for, so adding a use case needs **no router change**) and extracts `app` (name or verbatim store id), `store`, `window_days` (from time phrases, "1 năm"=365), `date_from/date_to`, `country`. A regex override copies an explicit package/trackId verbatim (LLMs mangle long ids) and the prompt forbids inventing an app when none is named. **Session context:** `Router._recent` keeps `{app, store, use_case}` per `session_id` (in-memory; back with Memory for durability) and feeds it to `_route_nl`, so a follow-up that omits the app ("tôi đoán điều này do lỗi gần đây") resolves against the previous turn, including platform. If the LLM is unavailable (MaaS down/slow or bad JSON), it falls back to `_heuristic_route` — a brittle keyword/stopword router kept only as a degraded backup. Explicit params always win over extracted ones; response language is auto-detected.
- **`core/registry.py`** — **auto-discovery is the central design rule.** It scans the `usecases/` and `connectors/` packages, imports every module, and collects concrete subclasses of `UseCase` / `AppDataConnector`. There is **no central list to edit** — dropping a new file into the package registers it. Modules named `base` or starting with `_` are skipped. `frameworks/base.py` has its own equivalent discovery in `framework_for()`.
- **`core/deps.py`** — the `Deps` container built once at startup. Its key method is **`connector_for(capability, store)` / `connectors_for(...)`**: use cases never name a data source, they request a *capability* (`reviews`, `metadata`, `search`, `downloads`, `ranking`, `category`) for a store and get connectors best-first per the `PREFERENCE` map. Callers iterate and **fall back** through them when one errors. The LLM is lazy (`deps.llm` property) so connector-only paths and tests run without LLM env vars.

### Extension points (the whole point of the layering)

- **Add a use case** → new file in `usecases/` subclassing `UseCase` (set `name`, `description`, `input_schema`; implement `run`). Auto-registered, routable by `action` name.
- **Add a data source** → new file in `connectors/` subclassing `AppDataConnector` (set `name`, `stores`, `capabilities()`; override only the capability methods you advertise — unsupported ones raise `NotSupported`). Add it to `PREFERENCE` in `core/deps.py` if it should be preferred for a capability.
- **Add an analytics framework** → new file in `frameworks/` subclassing `Framework` (used by the Hypothesis Checker; decomposes a claim into falsifiable `SubHypothesis` objects gated on connector capability).
- **Add an output channel** → new file in `outputs/` subclassing `OutputChannel`.

### Use-case execution patterns

**Sheet numbering ↔ code names.** Files map 1:1 to the "AI Agent UseCases" sheet: `uc1_store_metadata` (UC1), `uc2_reviews_sentiment` (UC2), `uc6_version_impact` (UC6 — before/after-release metric delta; historically misnamed `uc1_release_health`), `uc4_kpi_dashboard` (UC4), `uc7_competitive_comparison` (UC7), `uc8_competitor_weakness` (UC8), `uc9_trend_alert` (UC9), `uc10_insight_qa` (UC10 — an orchestrator that LLM-plans ≤2 of the other analyses, runs them, and synthesises a cited PM answer + action items). UC4 (KPI trend) and UC9 (anomaly alerts) read the **snapshot history** via the shared `snapshot_app()` helper in `usecases/base.py` — thin until snapshots accrue (ephemeral in a container → back with Memory). `hypothesis_check` is a standalone module, not part of the sheet. `uc6_version_impact` implements the metric-delta core of UC6; full feature-attribution (which feature drove the change) additionally needs the UC5 feature timeline. **UC5 (version feature tracking) is deferred** — no free source for per-version release notes (App Store needs an amp-api token; Google Play has none), so it requires a paid source.

The shipped use cases follow distinct shapes worth knowing before editing them.

**`uc1_store_metadata` (sheet UC1, single-shot).** Resolve → enriched `get_metadata` (title, category, price, icon, screenshots, description, version, rating) → iOS chart rank via `ios_charts` (Android has no free rank) → save a `Snapshot` (now carrying `rank`) → deltas vs the prior snapshot (rating / version-changed / rank) → iOS+Android concurrent, merge → persist the normalised row via `storage.save_table("metadata", …)`. Version history accrues from snapshots (no free full-history source).

**`uc2_reviews_sentiment` (sheet UC2, single-shot).** Resolve → fetch reviews over a window (`window_days` default 30, or `date_from`/`date_to`) via the reviews connectors with fallback → **deterministic** stats (volume, 1–5★ distribution, per-review language mix via `detect_lang`, **star-derived** sentiment, weekly trend) → **one bounded LLM call** clusters praise + complaint/bug themes (degrades to a note on timeout/no-LLM — sentiment never depends on it) → persist the raw review table. Sentiment is star-derived on purpose (cheap, no LLM-timeout risk); the LLM only does theme clustering on a sample. Competitor comparison is out of scope here (sheet UC7/UC8).

**`uc6_version_impact` (sheet UC6, single-shot).** `run` defaults `store` to `"both"` and analyses iOS + Android **concurrently** (`ThreadPoolExecutor`), then merges and warns if the two stores resolve to different-looking apps (`_names_match`). The core work in `_analyze_one` runs 7 numbered steps: resolve → metadata (+ **save a snapshot immediately**) → reviews split before/after `release_dt` → signals → verdict → LLM issue categorisation → summary. Critically there are **two parallel signal tracks**: review-based (`rating_delta`, velocity, `neg_share`) and metric-based (`metric_rating_delta` from the prior snapshot, which needs no review text — this is the iOS path). The first run only seeds the snapshot baseline; the trend appears from the second run on. Verdict precedence: review signals first, metric trend as fallback, flat = `inconclusive` (thresholds are module constants at the top of the file).

**`hypothesis_check` (multi-turn diagnostic).** This is the most intricate flow in the repo. Each turn: append the message to `deps.conversation` (keyed by `session_id`), then `_parse` has the LLM read the **entire conversation** and extract `{claim, missing, next_question}`. The claim is **re-derived from the full history every turn** — partial claim state is never persisted, which makes it robust. If any `REQUIRED_SLOTS` are missing it returns `status: "need_context"` with a question and waits for the next turn; only when complete does it `_analyze` and `clear` the session. `_analyze` resolves the app on a **single store per run** (normalises `"both"`/`"ios|android"`/multi → tries iOS then Android and notes the scope) — never let the parser emit a combined store literal — then runs a framework engine:

1. `framework_for(metric)` picks one of `frameworks/` (rating / revenue / downloads / retention).
2. `framework.sub_hypotheses(claim)` decomposes the claim into `SubHypothesis` objects, each carrying a `signal`, a `data_need` (connector capability), and a `necessary` flag.
3. `_gather` measures the signals; `_evaluate` resolves each sub-hypothesis to a status (`measured` / `supported` / `untestable` / `inconclusive` / `refuted`), **gating on whether the required capability is actually available**.
4. `_narrative` has the LLM render the verdict but must respect the **GATE**: if the `necessary` condition is `untestable` the verdict cannot be `supported`; if it is `refuted` the verdict must be `refuted`.

This GATE is the intellectual-honesty mechanism: a signal whose data isn't reachable (e.g. revenue/downloads on a metadata-only Sensor Tower token) is marked `untestable` and **caps the verdict** rather than letting the LLM fabricate confidence. When adding a framework, set the `necessary` flag deliberately and give each sub-hypothesis the right `data_need` — that is what wires it into the gate.

### Capability-gating and graceful degradation (critical invariant)

Connectors **degrade gracefully and must never crash the agent**. A capability is tried best-source-first and falls through on error: a store with no usable source for a capability yields a metrics-only report, not a failure. (Sensor Tower is iOS-scoped, so Android never calls it — Android reviews come straight from Google Play.) `main.handler` wraps everything and never 500s — it returns `{"status": "error", ...}`. `build_deps` swallows individual connector construction failures. When adding a connector or use case, preserve this: gate calls on `supports()` / `capabilities()`, catch `ConnectorError`, and prefer a degraded result over an exception.

### Data-source reality (2026)

- **iTunes** (free) — iOS **search + metadata** only (`averageUserRating`, rating count, current version + release date, release notes). Reviews are NOT served here — see `appstore_reviews`.
- **App Store reviews** (`appstore_reviews`, free) — iOS `reviews` with dates, **now available for free** (corrects the earlier "RSS dead" note). Primary source is the iTunes customer-reviews **RSS feed** (sorted newest→oldest, ~500 recent reviews ≈ ~1 month for a busy app; some pages return empty bodies at random, so empties are *retried*, not treated as end-of-data). Backfills deeper history from the undocumented `apps.apple.com` **Catalog API** (paginates by `offset` but **ignores `sort`** → filtered client-side). Both endpoints are undocumented + 429-prone, so requests are throttled. Net effect: UC1's iOS path can now do full review analysis **without** a Sensor Tower token (Sensor Tower still preferred when its token has reviews scope).
- **iOS charts** (`ios_charts`, free) — iOS `ranking` only, via Apple's Marketing-Tools top-charts RSS (`top-free` / `top-paid`; **no top-grossing**, max 100 entries). Reports an app's chart position or `rank=None` if it's outside the top 100. Sensor Tower is still preferred for ranking (exact, any depth, historical); this is the free fallback.
- **Google Play** (free, `google-play-scraper`) — Android metadata **and** reviews with dates; version is fuzzy.
- **Sensor Tower** (`SENSORTOWER_AUTH_TOKEN`, optional) — **iOS-only by design** (`stores = {"ios"}`): reviews-with-dates, downloads/revenue, rankings for the iOS gap, **subject to the token's API scope**. The day the token gains reviews scope, iOS review analysis lights up with no code change. Android is intentionally Google-Play-only, so Sensor Tower is never called for Android (widen its `stores` to change that).

### Other conventions

- **Bilingual by design** — `core/lang.py` detects Vietnamese vs English from the user's text and maps language → market (`vi`→VN store, `en`→US store). Use cases localise output; `params["lang"]` is auto-filled by the router.
- **Snapshots** (`storage/snapshots.py`) — append-only daily JSON-lines per app under `data/snapshots/`, letting the agent build its own rating/version time series (the fallback signal when there's no review baseline). Container storage is ephemeral; durable history needs AgentBase Memory.
- **LLM** (`core/llm.py`) — OpenAI-compatible (GreenNode MaaS) via `langchain_openai.ChatOpenAI`. `complete_json()` tolerates ```json fences, surrounding prose, and `<think>` reasoning blocks (Qwen gets `/no_think` auto-appended). Use it rather than parsing model output by hand. **Multi-model:** all MaaS models share one endpoint + key, so `deps.llm_for(model)` returns a per-model LLM (cached) — use cases can mix a fast model and a stronger one and call them concurrently. `deps.llm` is just `llm_for()` on the default `LLM_MODEL`. **Fail-fast:** every call is bounded by `LLM_TIMEOUT` (env, default 60s) with `LLM_MAX_RETRIES` (default 0) — a slow/down MaaS degrades the caller quickly (a note + fallback) instead of hanging; raise `LLM_TIMEOUT` only to wait out a borderline-slow model. Pick a fast instruction-tuned model (e.g. `google/gemma-4-31b-it`) for `LLM_MODEL`; reasoning models can exceed the timeout on bigger prompts.
- **Verdict ensemble** (`usecases/uc_hypothesis_check.py`) — `_narrative` can poll several models in parallel and **majority-vote** the verdict. Set `HYPOTHESIS_ENSEMBLE_MODELS` (comma-separated model paths) to enable; unset = a single call on `LLM_MODEL` (prior behaviour). The GATE is now also enforced in code (`_gate_verdict`): an untestable necessary condition caps the verdict at `inconclusive`, a refuted one forces `refuted` — guaranteed even if a model ignores the prompt. A split panel can't claim high confidence.
- **Conversation** (`core/conversation.py`) — swappable multi-turn store for the Hypothesis Checker; `LocalConversationStore` (JSON per session) locally, AgentBase Memory in production.

## Config & secrets

`.env`, `.greennode.json`, and `.agentbase/` are gitignored and contain live credentials — never commit them or echo their contents. Required LLM vars: `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` (provision via the `/agentbase-llm` skill). In production, store `SENSORTOWER_AUTH_TOKEN` via `/agentbase-identity`, not `.env`.

Deploy uses the GreenNode AgentBase skills (in the sibling `greennode-agentbase-skills` repo): `/agentbase-llm`, `/agentbase-deploy`, `/agentbase-monitor`, `/agentbase-identity`.

## Specs

Design docs live in `docs/specs/` (e.g. `2026-06-13-uc1-release-health-design.md`). Read the relevant spec before extending a use case.
