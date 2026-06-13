# App Intelligence Agent — Design Spec

**Date:** 2026-06-13
**Competition:** Claw-a-thon 2026 · Track: Automation & Integration
**Scope of this spec:** Modular AgentBase architecture + **UC1 (Release Health)** + **Hypothesis Checker** (UC2–UC4 deferred, but architecture must accept them as drop-in modules).

---

## 1. Problem & Value

A Product Manager / C-level wants to know, for **any app they choose**, whether a recent app update ("release") improved or hurt the product — measured by rating movement, review velocity, and what users are newly complaining about — without manually reading hundreds of reviews across stores.

**UC1 — Post-Release Health Check**: user picks any app → agent reports the health of its latest release.

The agent is **not limited to VNG apps** — the user supplies any app by name or store ID.

---

## 2. Data Sources (verified 2026-06-13)

| Source | Status | Provides | Auth |
|---|---|---|---|
| **iTunes Lookup/Search API** | ✅ works | App metadata, `averageUserRating`, `userRatingCount`, `averageUserRatingForCurrentVersion`, `version`, `currentVersionReleaseDate`, `releaseNotes`. Search any app by name. | none |
| **iTunes Reviews RSS** | ❌ dead | Returns 0 entries for all apps (incl. Instagram US) — Apple closed this feed. **Not used.** | — |
| **Google Play** | ⚠️ scraper | Review text + timestamp + rating + version (via `google-play-scraper`). Best-effort; may be rate/IP-limited in container. | none |
| **Sensor Tower API** (formerly data.ai / App Annie) | ✅ keyed | Rich: app details, **reviews with date+rating+version**, download/revenue estimates, category rankings. User **has an API key**. | `auth_token` query param |

**Key finding:** App Store per-review text is no longer free. Quantitative metrics (rating, count, version, release date) come free from iTunes; qualitative review text comes from **Google Play (free)** and **Sensor Tower (keyed)**.

> "Reading from data.ai" = calling `https://api.sensortower.com` with the user's `auth_token`. The data.ai website itself is login-gated and redirects to Sensor Tower.

---

## 3. Modular Architecture

Three pluggable layers. **Adding a new use case = drop one file + register it; no change to existing code.**

```
claw-a-thon-paynodegame/
├── main.py                  # GreenNodeAgentBaseApp: /health + /invocations router
├── core/
│   ├── router.py            # action -> use case; or NL message -> LLM intent routing
│   ├── registry.py          # auto-register use cases & connectors
│   ├── deps.py              # dependency container (connectors, llm, storage, outputs)
│   └── llm.py               # ChatOpenAI factory (Gemma-4-31b / Qwen-3-27B via MaaS)
│
├── connectors/              # DATA SOURCES (pluggable)
│   ├── base.py              # AppDataConnector interface + AppRef/AppMetadata/Review models
│   ├── itunes.py            # free: search + metadata
│   ├── googleplay.py        # free: reviews (scraper)
│   └── sensortower.py       # keyed: metadata + reviews + downloads/revenue + ranking
│
├── usecases/                # USE CASES (pluggable)
│   ├── base.py              # UseCase interface: name, description, input_schema, run(params, deps)
│   ├── uc1_release_health.py
│   └── uc_hypothesis_check.py
│   # uc2_*, uc3_*, uc4_* added later as separate files
│
├── frameworks/              # PRODUCT-ANALYTICS SUB-HYPOTHESIS LIBRARY (used by hypothesis checker)
│   ├── base.py              # Framework interface: metric -> list[SubHypothesis]
│   ├── revenue.py           # downloads x conversion x ARPPU; acquisition vs monetization
│   ├── rating.py            # release quality / regressions / reception
│   ├── downloads.py         # ASO / marketing / featuring / seasonality / competitor
│   └── retention.py         # onboarding / core loop / content cadence
│
├── outputs/                 # OUTPUT CHANNELS (pluggable)
│   ├── base.py
│   ├── markdown.py          # render report as markdown
│   └── webhook.py           # POST to Teams/Slack (used by UC2/UC4 later)
│
├── storage/
│   └── snapshots.py         # persist daily metric snapshots -> own time series
│
├── Dockerfile · requirements.txt · .env.example · README.md
```

### Interfaces

```python
# connectors/base.py
class AppDataConnector(ABC):
    name: str
    def capabilities(self) -> set[str]      # subset of {search, metadata, reviews, downloads, ranking}
    def is_available(self) -> bool           # e.g. Sensor Tower only if token present
    def search_app(self, term, store) -> list[AppRef]
    def get_metadata(self, app_id, store) -> AppMetadata
    def get_reviews(self, app_id, store, start_date, end_date) -> list[Review]
    # optional (capability-gated; raise NotSupported if not in capabilities()):
    def get_downloads(self, app_id, store, start_date, end_date) -> list[DownloadPoint]   # revenue + units
    def get_ranking(self, app_id, store, category, date) -> RankPoint

# usecases/base.py
class UseCase(ABC):
    name: str            # "uc1_release_health"
    description: str
    input_schema: dict
    def run(self, params: dict, deps: Deps) -> dict
```

- **Registry** discovers all `UseCase` and `AppDataConnector` subclasses at startup.
- **Deps** injects: best-available connector per capability, the LLM, storage, outputs.
- Connector selection is capability + availability based: for `reviews`, prefer Sensor Tower (if token) else Google Play; for `metadata`/`search`, iTunes is the free default.

### Runtime contract (AgentBase, HARD requirements)

- Listen on **port 8080**.
- `GET /health` → 200 (`@app.ping` → `PingStatus.HEALTHY`).
- `POST /invocations` (SDK convention) → `@app.entrypoint handler(payload, context)`.

### Request shape

```jsonc
// Explicit (for API / future scheduled calls):
{ "action": "uc1_release_health", "params": { "app": "Instagram", "store": "ios", "country": "us" } }

// Natural language (LLM routes + extracts params):
{ "message": "kiểm tra sức khoẻ bản cập nhật mới nhất của Instagram trên iOS" }
```

`app` may be an app name (resolved via search) or a store ID.

---

## 4. UC1 — Post-Release Health Check (detailed flow)

```
Input: { app, store (ios|android), country }

1. RESOLVE APP
   - If app is an ID -> use directly.
   - Else search_app(app, store) -> pick top match -> app_id + canonical name.

2. METADATA + RELEASE
   - get_metadata -> version, currentVersionReleaseDate (= release_date), avgRating, ratingCount, releaseNotes.
   - Persist snapshot { date, app_id, version, avgRating, ratingCount } to storage.

3. FETCH REVIEWS AROUND RELEASE
   - window = [release_date - 14d, now]
   - get_reviews via best connector:
       Sensor Tower (date+rating+version) if token; else Google Play (free).
   - Split into BEFORE (< release_date) vs AFTER (>= release_date).

4. COMPUTE HEALTH SIGNALS
   - rating delta: avg(after) - avg(before)
   - review velocity: reviews/day after vs before
   - negative share shift: %(<=2 star) after vs before
   - flag REGRESSION if rating delta <= -0.2 OR negative share +10pp.

5. LLM ANALYSIS (Gemma/Qwen)
   - Categorize AFTER negative reviews -> {crash, performance, UX, auth, payment, content, other}
   - Rank issue categories by frequency, pull representative quotes.

6. OUTPUT
   - Structured JSON + markdown summary, e.g.:
     "Instagram v300.1 (released 2026-06-10): rating 4.50 -> 4.42 (-0.08),
      review velocity +120%/day, negative share +9pp.
      Top new complaints: crash on reels (18), login loop (11)."
```

**First-run caveat:** snapshot time-series needs ≥2 runs to show before/after on *metrics*. Review-based before/after works on the first run because reviews carry their own dates. For demo, seed a baseline snapshot.

**Graceful degradation:** no Sensor Tower token → use Google Play reviews; Google Play blocked → metrics-only report (rating/velocity from iTunes), clearly noting review text was unavailable.

---

## 4-bis. Hypothesis Checker (diagnostic / causal)

**Purpose:** Turn an executive's informal gut-feeling claim about a product into a data-backed verdict with evidence — the diagnostic counterpart to UC1's descriptive report. Reuses the same connectors + LLM + storage, and adds a `downloads/revenue` connector capability (Sensor Tower) and a `frameworks/` sub-hypothesis library.

**Input:** one informal natural-language statement, e.g.
> "Tôi nghĩ tính năng X làm tăng revenue của sản phẩm Y trong build Z."

**Why it is domain-expert, not a chatbot:** the agent does NOT test the literal sentence. It decomposes the claim into falsifiable **professional sub-hypotheses** using a product-analytics framework keyed to the claimed metric, tests each against data, and aggregates a calibrated verdict with explicit confounders and causation caveats.

### Pipeline (6 stages)

```
1. PARSE — LLM -> structured Claim:
   { entity, metric (revenue|rating|downloads|retention|...), direction,
     cause (hypothesized driver), build/version, timeframe?, baseline? }

2. SLOT-FILL CONTEXT — detect missing slots required for a rigorous test, ASK the user:
   - exact app (resolve -> app_id + store)
   - which version is "build Z" + its release date
   - what "feature X" maps to (release-note text / keywords)
   - analysis window (default: 30d post-build)
   - baseline (prior build / same-length window before)
   Context-gathering mechanism: SEE OPEN DECISION D2 (multi-turn vs stateless slot-fill).

3. GENERATE PROFESSIONAL SUB-HYPOTHESES (framework keyed to metric).
   Example — revenue framework:
     H1 Did revenue estimate actually rise in [window after Z] vs baseline?  (necessary condition)
     H2 Does the rise align temporally with Z's release (not pre-existing trend)?
     H3 Is the rise acquisition-driven (downloads up) or monetization-driven (ARPPU up)?
     H4 Do reviews mention feature X positively post-release? (adoption signal)
     H5 Is there a dominant confounder (seasonality, marketing, price, competitor event)?
   Framework library covers: revenue, rating/quality, downloads/acquisition, retention.

4. GATHER EVIDENCE per sub-hypothesis:
   - revenue/downloads: Sensor Tower sales_report_estimates (before vs after vs baseline)
   - version timeline: iTunes currentVersionReleaseDate + Sensor Tower version history
   - feature mention: review keyword search post-release (Sensor Tower / Google Play)
   - confounders: rating trend, review themes, competitor ranking shifts (if available)

5. EVALUATE: each sub-hypothesis -> { supported | refuted | inconclusive, confidence, evidence[] }
   -> aggregate verdict on the MAIN claim:
      Supported (high/med/low) | Partially supported | Refuted | Inconclusive (insufficient data)

6. OUTPUT (structured JSON + markdown):
   VERDICT + confidence
   EVIDENCE FOR  (numbers + source tags)
   EVIDENCE AGAINST / CAVEATS (confounders; "revenue is a Sensor Tower ESTIMATE, not booked revenue";
                               correlation != causation)
   WHAT WOULD CONFIRM IT (data not in public sources, e.g. ARPPU by exposed cohort)
```

### Design rules

- **Intellectual honesty is a feature, not a flaw.** Always surface the strongest confounder, label estimates as estimates, and never assert causation from observational data. This is what makes it credible to C-level.
- **Necessary-condition gating:** if H1 (metric didn't move in claimed direction) is refuted, the verdict is "Refuted" regardless of other signals — report it plainly.
- **Graceful degradation:** revenue/downloads hypotheses require the Sensor Tower token. Without it, the checker restricts to rating/review-based metrics and says so.
- **Modularity:** new use case `usecases/uc_hypothesis_check.py` + `frameworks/` (one file per metric framework) + `connectors` gain optional `downloads`/`revenue` capability. UC1 untouched.

### Request shape

```jsonc
{ "action": "hypothesis_check",
  "params": { "statement": "tôi nghĩ tính năng X làm tăng revenue của Y ở build Z" } }
// or natural language via { "message": "..." } routed by the LLM
```

---

## 5. Configuration (env vars)

| Var | Purpose | Secret | Where |
|---|---|---|---|
| `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` | MaaS LLM (Gemma/Qwen) | key=yes | `.env` (local), platform-injected (prod) |
| `SENSORTOWER_AUTH_TOKEN` | data.ai/Sensor Tower API | **yes** | `.env` local; `/agentbase-identity` APIKEY for prod. **Never committed, never pasted in chat.** |
| `DEFAULT_STORE` / `DEFAULT_COUNTRY` | defaults (ios, us) | no | `.env` |

---

## 6. Out of scope (this spec)

- UC2 (competitor weekly), UC3 (issue ranking), UC4 (ranking monitor) — architecture supports them as new `usecases/*.py`, but they are **not built now**.
- Scheduling/cron — deferred with UC2/UC4.
- Persistent DB — `storage/` uses simple file/JSON snapshots; revisit if needed.

---

## 6-bis. Resolved decisions

- **D1 — Build sequencing → RESOLVED: UC1 first, then Hypothesis Checker.** Two separate use cases. UC1 is built first as the foundation (connectors + metadata + reviews + delta computation); the Hypothesis Checker layers on top and reuses all of UC1's plumbing.
- **D2 — Context-gathering → RESOLVED: multi-turn conversation.** The Hypothesis Checker holds a conversation across turns using `X-GreenNode-AgentBase-Session-Id` + **AgentBase Memory service**, asking clarifying questions like an analyst until all required slots are filled, then runs the analysis. (UC1 itself is single-shot and needs no memory; memory is introduced when the Hypothesis Checker is built.)

## 7. Risks & open items

1. **Google Play scraping reliability** inside the 2vCPU/4GB container (IP limits). Mitigation: capability fallback chain — other sources still serve metrics.
2. **Sensor Tower plan coverage → CONFIRMED limited (2026-06-13).** The provided token has **metadata-only scope**: `/v1/ios/apps` returns 200, but `review/get_reviews`, `sales_report_estimates`, `search_entities`, and `version_history` all return 401/403. Verified via `tests/verify_sensortower.py`. Implication: ST currently adds nothing over iTunes; **reviews/downloads/revenue features need a reviews-scoped token**. The connector advertises these capabilities and **auto-activates** when the token gains scope (no code change). Web-dashboard access (data.ai) is session-based and separate from API scope; not used (ToS/fragility).
   - **iOS review text → no reliable free source (2026).** iTunes reviews RSS is dead (0 entries for all apps); `amp-api` token no longer extractable from the store page; `app-store-scraper` returns 0. **Decision: iOS = metrics-only + snapshot trend; Android = full Google Play reviews.** iOS reviews activate later via a reviews-scoped Sensor Tower token or a dropped-in `connectors/appfollow.py`.
3. **OpenClaw vs Custom Agent** — this design assumes the **Custom Agent** runtime (custom Docker). Confirm the allocated "3 OpenClaw instances" allow a Custom Agent runtime; if only OpenClaw (Telegram/Zalo templates) is available, the interface layer changes (bot front-end) though the core modules stay the same.
4. **Snapshot persistence across redeploys** — container storage is ephemeral; snapshots reset on redeploy unless backed by AgentBase Memory or external store. Acceptable for demo.
