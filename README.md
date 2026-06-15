# Veridex — App Intelligence Agent

> Claw-a-thon 2026 · Track: **Automation & Integration** · Platform: **GreenNode AgentBase**

**Veridex** ("veritas" + "index" — a truth index over app-store signals) turns public
App Store / Google Play signals — for both **apps and games** (metadata, reviews, ratings,
ranks) — into evidence-based
product decisions: store metadata, reviews & sentiment, KPI trends, release-health checks,
competitor comparison & weaknesses, anomaly alerts (with per-user Telegram subscriptions),
free-form Q&A, and data-backed hypothesis verdicts. Bilingual VI/EN.

---

## Problem · User · Solution · Value

- **Problem.** PMs and C-level form opinions about a release ("the new build hurt
  ratings", "this feature drove revenue") but verifying them means manually reading
  reviews and stitching together store metrics across iOS/Android.
- **User.** Product Managers, Growth/Marketing, and C-level who need a fast,
  evidence-based read on a release — for their own app or a competitor's.
- **Solution.** A modular agent on AgentBase that resolves any app, pulls metrics
  and reviews around its latest release, and produces a structured health report.
  A second use case (in progress) takes an informal hypothesis and returns a
  data-backed verdict with confounders and caveats.
- **Value.** Minutes instead of hours; intellectually honest (labels estimates as
  estimates, correlation vs causation) so it is safe to act on.

---

## What works today (UC1 — Release Health Check)

Given an app name or store id, the agent:
1. **Resolves** the app (search or direct id) on iOS or Android.
2. **Reads metadata** + the latest release (version, release date, notes) and stores
   a daily **snapshot** (builds its own time series).
3. **Pulls reviews** around the release and splits them **before vs after**.
4. **Computes signals**: rating delta, review velocity, negative-share shift.
5. **Categorises** post-release complaints with the LLM (crash / perf / UX / auth /
   payment / …).
6. **Verdict**: 🟢 healthy · 🔴 regression · 🟡 inconclusive — with a markdown report.

### In progress (next phase)
- **Hypothesis Checker** — multi-turn, evidence-based verdict on an informal claim
  (e.g. *"feature X raised revenue in build Z"*). See `docs/specs/`.
- **UC2–UC4** (competitor weekly, issue ranking, ranking monitor) — drop-in modules.

---

## Data sources

| Source | Cost | Provides | Notes |
|---|---|---|---|
| **iTunes Search/Lookup** | free | iOS metadata, ratings, version, release date | reviews RSS is dead → metadata only |
| **Google Play** (`google-play-scraper`) | free | Android metadata + reviews w/ dates | best-effort; version is fuzzy |
| **Sensor Tower** (data.ai / App Annie) | **keyed** | reviews-with-dates, downloads/revenue, rankings — **subject to the token's API scope** | set `SENSORTOWER_AUTH_TOKEN`; premium accuracy |

Connectors are capability-gated and **degrade gracefully**: each capability tries
sources best-first and **falls back** when one errors, so a limited Sensor Tower
token (e.g. metadata-only scope → reviews return 401) automatically falls through to
Google Play; no review source for a store → metrics-only report, never a crash.

### iOS review text (current reality, 2026)
Apple closed the free routes: the iTunes reviews RSS feed is dead and the
`amp-api` token is no longer extractable. So **iOS runs are metrics-only**: rating,
version, release date, plus a **snapshot trend** (rating + new-ratings movement vs the
last run — the agent builds its own time series). **Android** gets full review
analysis via Google Play.

> **Extending to iOS reviews later — no code change.** The Sensor Tower connector
> already advertises `reviews` for iOS. The day your `SENSORTOWER_AUTH_TOKEN` gains
> reviews scope, `get_reviews` returns 200 instead of 401 and the fallback chain uses
> it for iOS automatically. Alternatively, drop a new `connectors/appfollow.py`
> (or Appbot/AppTweak) implementing `AppDataConnector` — the registry picks it up.

> **Known limitation.** On free sources, very high-volume apps return only the newest
> N reviews — which can all post-date the release, leaving no "before" baseline
> (verdict falls back to the snapshot trend). Date-bounded Sensor Tower queries and
> accumulated snapshots resolve this.

All data is **public/anonymised** per the competition rulebook. No customer PII.

---

## Architecture (modular — drop a file to extend)

```
main.py            # AgentBase entrypoint: port 8080, GET /health, POST /invocations
core/              # llm · registry (auto-discovery) · deps (connector selection) · router
connectors/        # itunes · googleplay · sensortower   (implement AppDataConnector)
usecases/          # uc1_store_metadata · uc2_reviews_sentiment · uc6_version_impact · hypothesis_check
outputs/           # markdown  (+ webhook later)
storage/           # daily metric snapshots
```

- Add a **use case**: new file in `usecases/` subclassing `UseCase` → auto-registered,
  routable by `action` name.
- Add a **data source**: new file in `connectors/` subclassing `AppDataConnector`.

---

## Run locally

```bash
python3 -m venv venv && source venv/bin/activate   # Python 3.10+ (Docker uses 3.12)
pip install -r requirements.txt
cp .env.example .env                               # fill LLM_* (and optional SENSORTOWER_AUTH_TOKEN)
python main.py                                     # serves on http://0.0.0.0:8080
```

Invoke (explicit action):
```bash
curl -X POST http://127.0.0.1:8080/invocations -H "Content-Type: application/json" -d '{
  "action": "uc6_version_impact",
  "params": {"app": "Spotify", "store": "ios", "country": "us"}
}'
```

Invoke (natural language):
```bash
curl -X POST http://127.0.0.1:8080/invocations -H "Content-Type: application/json" \
  -d '{"message": "check the health of Instagram'\''s latest Android update"}'
```

Health check:
```bash
curl http://127.0.0.1:8080/health
```

## Tests

```bash
./venv/bin/python tests/test_uc6_version_impact.py            # synthetic + live iTunes + Google Play
./venv/bin/python tests/test_uc6_version_impact.py --no-live  # offline analytics asserts only
./venv/bin/python tests/verify_uc1_store_metadata.py          # sheet UC1 metadata (live)
./venv/bin/python tests/verify_uc2_reviews_sentiment.py      # sheet UC2 reviews & sentiment (live)
```

## Deploy

Use the AgentBase skills: `/agentbase-llm` (provision MaaS key), `/agentbase-deploy`
(build → push → runtime), `/agentbase-monitor` (logs/metrics). For the Sensor Tower
token in production, store it via `/agentbase-identity` rather than `.env`.

## Config (`.env`)

`LLM_MODEL` · `LLM_BASE_URL` · `LLM_API_KEY` (GreenNode MaaS) · `SENSORTOWER_AUTH_TOKEN`
(optional) · `DEFAULT_STORE` · `DEFAULT_COUNTRY` · `MEMORY_ID` (added with the
Hypothesis Checker).
