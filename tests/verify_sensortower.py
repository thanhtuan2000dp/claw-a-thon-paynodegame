"""Verify the Sensor Tower API against a real token, WITHOUT exposing it.

Loads SENSORTOWER_AUTH_TOKEN from .env, probes the endpoints the connector uses,
and prints ONLY: the path (no token), HTTP status, and the response's top-level
shape / first-item keys / a tiny sample. The token is never printed.

Use the output to confirm which endpoints your plan includes and to fix field
names in connectors/sensortower.py if they differ.

Run:  ./venv/bin/python tests/verify_sensortower.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE = "https://api.sensortower.com"
TOKEN = os.environ.get("SENSORTOWER_AUTH_TOKEN", "")

# Spotify iOS trackId (a stable, well-known app for probing).
APP_IOS = "324684580"

PROBES = [
    ("metadata", f"/v1/ios/apps", {"app_ids": APP_IOS, "country": "US"}),
    ("search", f"/v1/ios/search_entities", {"entity_type": "app", "term": "spotify", "limit": 3}),
    (
        "reviews",
        f"/v1/ios/review/get_reviews",
        {"app_id": APP_IOS, "country": "US", "start_date": "2026-05-01", "end_date": "2026-06-13", "limit": 5},
    ),
    (
        "downloads",
        f"/v1/ios/sales_report_estimates",
        {"app_ids": APP_IOS, "countries": "US", "date_granularity": "daily", "start_date": "2026-06-01", "end_date": "2026-06-13"},
    ),
    ("version_hist", "/v1/ios/apps/version_history", {"app_ids": APP_IOS, "country": "US"}),
    ("rating", "/v1/ios/review/get_rating", {"app_id": APP_IOS, "country": "US"}),
]


def _shape(data) -> str:
    """Describe JSON structure without dumping large/sensitive content."""
    if isinstance(data, dict):
        keys = list(data.keys())
        out = f"dict keys={keys[:12]}"
        # peek into first list-valued key
        for k in keys:
            if isinstance(data[k], list) and data[k]:
                first = data[k][0]
                if isinstance(first, dict):
                    out += f" | '{k}'[0] keys={list(first.keys())[:14]}"
                break
        return out
    if isinstance(data, list):
        out = f"list len={len(data)}"
        if data and isinstance(data[0], dict):
            out += f" | [0] keys={list(data[0].keys())[:14]}"
        return out
    return f"{type(data).__name__}: {str(data)[:80]}"


def main() -> None:
    if not TOKEN:
        print("❌ SENSORTOWER_AUTH_TOKEN is empty. Put it in .env first.")
        return
    print(f"Token loaded (len={len(TOKEN)}, redacted). Probing {BASE} ...\n")
    for label, path, params in PROBES:
        full = {**params, "auth_token": TOKEN}
        try:
            resp = httpx.get(f"{BASE}{path}", params=full, timeout=25.0)
        except httpx.HTTPError as exc:
            print(f"[{label:9}] {path}  ERROR: {exc}")
            continue
        status = resp.status_code
        try:
            body = resp.json()
            shape = _shape(body) if status == 200 else f"error body: {json.dumps(body)[:240]}"
        except Exception:  # noqa: BLE001
            shape = f"(non-JSON, {len(resp.text)} chars) {resp.text[:160]}"
        # redact token if it ever appears in an echoed error
        shape = shape.replace(TOKEN, "<redacted>") if TOKEN else shape
        flag = "✅" if status == 200 else ("🔒" if status in (401, 403) else "⚠️")
        print(f"[{label:9}] {flag} {status}  {path}\n            {shape}\n")


if __name__ == "__main__":
    main()
