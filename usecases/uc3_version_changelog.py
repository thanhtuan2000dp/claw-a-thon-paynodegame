"""Sheet UC3 — Version changelog timeline.

List how an app changed across versions: an ordered timeline of the versions the
agent has observed, each with the date it first appeared, its store release date,
and the store changelog (release notes) captured for that version.

Data reality: app stores expose only the **current** version's release notes (no
free per-version history — App Store's amp-api ``versionHistory`` needs a token,
Google Play has none). So this use case **accrues** the timeline from the daily
snapshot store: every run records the live version + its notes, and a new entry
appears here whenever the version number changes between runs. Day one shows just
the current version; the history fills in as the app ships updates over time
(ephemeral in a container → back with AgentBase Memory for durable history).

Distinct from uc6_version_impact (does a release HURT/HELP metrics?) and
uc4_kpi_dashboard (rating/rank trend). This one answers *what shipped, and when*.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from core.lang import detect_lang, lang_name, market_for
from usecases.base import UseCase, looks_like_id, snapshot_app


class VersionChangelogUseCase(UseCase):
    name = "uc3_version_changelog"
    description = (
        "Version changelog timeline — list how an app changed across its versions: an "
        "ordered list of versions with the date each appeared and its store release "
        "notes (what shipped). Use for 'liệt kê thay đổi qua các version', 'lịch sử "
        "cập nhật/phiên bản', 'changelog của app', 'app đã thay đổi gì qua các bản', "
        "'version history / what changed over time'. NOT whether a release helped or "
        "hurt metrics (uc6_version_impact), the rating/rank trend (uc4_kpi_dashboard), "
        "or a head-to-head with rivals (uc7_competitive_comparison)."
    )
    input_schema = {
        "app": "app name to search, or a store id",
        "store": "ios | android | both (default both)",
        "country": "two-letter store country (default from language)",
    }

    def run(self, params: dict, deps, context=None) -> dict:
        store = (params.get("store") or "both").lower()
        app_query = (params.get("app") or "").strip()
        if not app_query:
            return {"use_case": self.name, "error": "missing 'app' parameter"}
        lang = (params.get("lang") or detect_lang(app_query)).lower()
        market_country, review_lang = market_for(lang)
        country = params.get("country") or market_country

        # A store id pins the platform; otherwise "both" runs iOS + Android concurrently.
        if store in ("both", "all", "cross", "cross_platform"):
            if app_query.isdigit():
                store = "ios"
            elif looks_like_id(app_query, "android"):
                store = "android"
        if store in ("both", "all", "cross", "cross_platform"):
            with ThreadPoolExecutor(max_workers=2) as ex:
                futs = {s: ex.submit(self._one, app_query, s, country, review_lang, lang, deps)
                        for s in ("ios", "android")}
                platforms = {s: f.result() for s, f in futs.items()}
            return {"use_case": self.name, "mode": "cross_platform", "lang": lang,
                    "app_query": app_query, "platforms": platforms}
        return self._one(app_query, store, country, review_lang, lang, deps)

    def _one(self, app_query, store, country, review_lang, lang, deps) -> dict:
        # snapshot_app records today's live version + notes, then returns full history.
        snap = snapshot_app(app_query, store, deps, country, review_lang)
        if snap is None:
            return {"use_case": self.name, "error": f"could not resolve/fetch '{app_query}' on {store}"}
        meta, history = snap["meta"], snap["history"]
        vi = lang == "vi"

        timeline = self._timeline(history)
        first_observation = len(timeline) < 2
        notes: list[str] = []
        if first_observation:
            # The most common "is this broken?" case: a single version on the first
            # run. Spell out that this is expected, not an error.
            notes.append(
                "✅ Không phải lỗi: đây là lần đầu theo dõi nên mới chỉ thấy phiên bản hiện tại. "
                "Store chỉ công bố release notes của bản mới nhất, nên lịch sử được tích luỹ dần — "
                "mỗi khi app ra bản mới, một mục version sẽ được thêm vào danh sách này."
                if vi else
                "✅ Not an error: this is the first observation, so only the current version shows. "
                "Stores publish only the latest version's notes, so history accrues over time — "
                "each new app release adds a version entry here."
            )
            notes.append(
                "Muốn xem ngay toàn bộ lịch sử version cũ thì cần nguồn trả phí (App Store amp-api / Sensor Tower có scope)."
                if vi else
                "To see the full back-history of older versions immediately, a paid source is needed (App Store amp-api / scoped Sensor Tower)."
            )
        else:
            notes.append(
                "Lịch sử được tích luỹ qua snapshot kể từ lần theo dõi đầu tiên (không backfill các version trước đó)."
                if vi else
                "History is accrued from snapshots since first tracking (older versions are not backfilled)."
            )
        if timeline and not timeline[0].get("release_notes"):
            notes.append(
                "Bản hiện tại không kèm release notes trên store (nhà phát triển để trống)."
                if vi else
                "The current version ships no release notes on the store (developer left it blank)."
            )

        highlights = self._highlights(meta.name, timeline, deps, notes, lang)

        result = {
            "use_case": self.name, "lang": lang,
            "app": {"app_id": meta.app_id, "name": meta.name, "store": store, "category": meta.category},
            "current_version": meta.version,
            "first_observation": first_observation,  # consumer flag: day-1 vs accrued history
            "versions": timeline,
            "highlights": highlights,
            "notes": notes,
        }
        result["summary"] = self._summarise(result, lang)
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _timeline(history) -> list[dict]:
        """Collapse the per-day snapshot history into one entry per distinct version,
        chronological. A new entry starts whenever the version number changes between
        consecutive snapshots. ``first_seen`` is when the agent first observed that
        version; release notes are the first non-empty notes captured for it."""
        rows = sorted(history, key=lambda s: s.captured_at)
        versions: list[dict] = []
        for s in rows:
            if not s.version:
                continue
            if versions and versions[-1]["version"] == s.version:
                cur = versions[-1]
                cur["last_seen"] = s.captured_at
                # Backfill notes/release date if an earlier snapshot lacked them.
                if not cur.get("release_notes") and s.release_notes:
                    cur["release_notes"] = s.release_notes
                if not cur.get("release_date") and s.current_version_release_date:
                    cur["release_date"] = s.current_version_release_date
                continue
            versions.append({
                "version": s.version,
                "first_seen": s.captured_at,
                "last_seen": s.captured_at,
                "release_date": s.current_version_release_date,
                "release_notes": s.release_notes,
            })
        versions.reverse()  # newest version first
        return versions

    def _highlights(self, app_name, timeline, deps, notes, lang) -> list[str]:
        """LLM read of what evolved across the captured versions. Optional — degrades
        to a note if the LLM is unavailable, and is skipped when there is nothing to
        compare (fewer than 2 versions with notes)."""
        with_notes = [v for v in timeline if v.get("release_notes")]
        if len(with_notes) < 2:
            return []
        block = "\n\n".join(
            f"v{v['version']} (released {v.get('release_date') or v['first_seen']}):\n{v['release_notes']}"
            for v in with_notes
        )
        prompt = (
            "You are a product analyst reading an app's version changelog (newest first). "
            f"For '{app_name}', summarise in 3-5 concise bullets how the app evolved across "
            "these versions: recurring themes, notable new features, and the apparent product "
            "direction. Base every claim only on the notes below; do not invent features. "
            f"Write the bullets in {lang_name(lang)}. Return ONLY JSON: "
            '{"highlights": ["...", "..."]}.\n\n' + block
        )
        try:
            data = deps.llm.complete_json(prompt)
        except Exception as exc:  # noqa: BLE001 - LLM optional; degrade cleanly
            notes.append(f"Changelog highlights skipped (LLM unavailable: {exc}).")
            return []
        hl = data.get("highlights") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return [str(x) for x in (hl or [])][:5]

    def _summarise(self, result: dict, lang: str) -> str:
        n = len(result["versions"])
        you = result["app"]["name"]
        cur = result.get("current_version")
        if result.get("first_observation"):
            # Frame day-1 as "tracking started", not an empty/failed result.
            return (f"Bắt đầu theo dõi lịch sử phiên bản {you} từ hôm nay — hiện tại v{cur}. "
                    f"Các version mới sẽ được thêm vào khi app cập nhật."
                    if lang == "vi" else
                    f"Started tracking {you}'s version history today — currently v{cur}. "
                    f"New versions will be added as the app updates.")
        if lang == "vi":
            return (f"Lịch sử phiên bản {you}: {n} version quan sát được, "
                    f"hiện tại v{cur}.")
        return (f"Version history for {you}: {n} version(s) observed, "
                f"currently v{cur}.")
