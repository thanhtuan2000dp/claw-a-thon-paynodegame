# Design — Sheet UC1 (Store Metadata) + UC2 (Reviews & Sentiment)

- **Date:** 2026-06-14
- **Author:** brainstormed with Tuấn
- **Status:** approved, implementing

## Context

The sheet "AI Agent UseCases.xlsx" numbers 10 use cases. The shipped
`uc1_release_health` actually matches **sheet UC6** (Version impact report:
before/after-release metric delta). This spec builds the **true sheet UC1 and
UC2** as new use cases, reusing the existing connectors, LLM, snapshot store,
bilingual output, and resolve logic. `hypothesis_check` stays a separate module,
not part of the sheet numbering.

Naming: new files `uc1_store_metadata.py` / `uc2_reviews_sentiment.py`. The old
`uc1_release_health` was **renamed to `uc6_version_impact`** (class
`VersionImpactUseCase`, action `uc6_version_impact`) so the code maps 1:1 to the
sheet; tests/docs/router were updated accordingly.

## Decisions (locked)

1. **Sentiment** = star-derived for all reviews (1–2 negative / 3 neutral / 4–5
   positive); LLM only clusters themes on a bounded sample (avoids the 50s LLM
   timeout; mirrors the existing UC1 `_categorise` pattern).
2. **Scope** = single app (iOS+Android). Competitor dimension deferred to UC7/UC8.
3. **Metadata** = best-effort current fields + self-built snapshot history; iOS
   rank via `ios_charts`; **no** Android rank, **no** full version history (no
   free source).
4. **Output** = structured dict + Markdown + persist the raw table to storage for
   downstream use cases.

## Shared refactor

Add `looks_like_id(app, store)` and `resolve_app(app_query, store, deps, country,
lang)` to `usecases/base.py`. New use cases import them. `uc6_version_impact`
keeps its private copies (left untouched to protect the shipping path).

## Data-model changes (additive, default None — no impact on existing code)

- `AppMetadata`: + `category`, `price`, `icon_url`, `screenshot_urls: list`,
  `description`.
- `Snapshot`: + `rank` (Optional[int]).
- `SnapshotStore`: + `save_table(kind, app_id, store, rows)` → JSON under
  `data/<kind>/` for UC1 metadata rows and UC2 raw review rows.

## Connector changes

- `itunes.get_metadata` / `googleplay.get_metadata`: populate the new
  `AppMetadata` fields from the raw payload (defensive `.get`).

## UC1 — `uc1_store_metadata` (sheet UC1)

- **Input:** `app`, `store` (ios|android|both, default both), `country`, `lang`.
- **Steps:** resolve → `get_metadata` (now enriched) → iOS rank via `ios_charts`
  (`top-free`; Android → note "no free rank") → save `Snapshot` (with rank) →
  compute deltas vs previous snapshot (rating / version-changed / rank) →
  iOS+Android concurrent, merge → persist metadata row.
- **Output:** `{app, metadata{...}, ranking{...}, history{rating_delta,
  version_changed, rank_delta, baseline_date}, summary}`.

## UC2 — `uc2_reviews_sentiment` (sheet UC2)

- **Input:** `app`, `store`, `country`, `lang`, `window_days` (default 30) or
  `date_from`/`date_to` (ISO).
- **Steps:** resolve → fetch reviews in window (connectors w/ fallback) →
  deterministic stats: volume, star distribution (1–5 count+%), language
  distribution (per-review `detect_lang`, vi/en only — note limit), sentiment
  split (star-derived), weekly trend (volume + avg rating + sentiment per ISO
  week) → LLM theme clusters on a bounded sample for praise + complaint/bug
  (degrade to a note on LLM failure) → iOS+Android concurrent → persist raw table.
- **Output:** `{app, window, totals, star_distribution, language_distribution,
  sentiment, weekly_trend, themes{praise, complaints}, sample_reviews, summary}`.

## Output rendering

Add `_render_uc1_store_metadata` and `_render_uc2_reviews_sentiment` to
`MarkdownOutput` (bilingual labels, same style as the UC1 renderer). Generic
fallback (`summary`) covers them until then.

## Testing

`tests/verify_uc1_store_metadata.py` and `tests/verify_uc2_reviews_sentiment.py`
— live against Zalo (iOS 579523206 / Android com.zing.zalo), skip on network
failure, assert shape + invariants (sorted, in-window, distributions sum to
total). Run with `venv/bin/python`.

## Known limitations (surfaced to the user)

- Android ranking: no free source.
- Full version history: not available free → history accrues from snapshots.
- Language detection: vi/en only (`core/lang.py`).
- LLM theme clustering: bounded sample + 50s timeout; may be skipped (noted) when
  the MaaS model is slow.
