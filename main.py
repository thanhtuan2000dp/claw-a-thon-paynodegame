"""App Intelligence Agent — AgentBase entrypoint.

Thin runtime wrapper: satisfies the platform contract (port 8080, GET /health)
and delegates every request to the modular Router. All business logic lives in
core/ · connectors/ · usecases/ · outputs/ (none of which import this module),
so the agent stays testable and use cases stay drop-in.
"""

import os
from datetime import datetime

from dotenv import load_dotenv
from greennode_agentbase import GreenNodeAgentBaseApp, PingStatus, RequestContext
from starlette.responses import HTMLResponse

from core.deps import build_deps
from core.router import Router
from outputs.markdown import MarkdownOutput

load_dotenv()

app = GreenNodeAgentBaseApp()
_markdown = MarkdownOutput()
_router: Router | None = None

# Built-in web chat UI served at GET / (same-origin -> no CORS). Loaded once.
_UI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "chat.html")
try:
    with open(_UI_PATH, encoding="utf-8") as _fh:
        _CHAT_HTML = _fh.read()
except OSError:
    _CHAT_HTML = "<h1>App Intelligence Agent</h1><p>POST /invocations to use the agent.</p>"


async def _chat_ui(request):  # GET / -> chat interface
    return HTMLResponse(_CHAT_HTML, headers={"Cache-Control": "no-store"})


app.add_route("/", _chat_ui, methods=["GET"])


def _router_instance() -> Router:
    # Lazy build so a missing LLM key never blocks the health check / boot.
    global _router
    if _router is None:
        _router = Router(build_deps())
    return _router


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    """POST /invocations entrypoint.

    payload: {"action": "...", "params": {...}}  OR  {"message": "..."}
    """
    try:
        result = _router_instance().handle(payload, context)
    except Exception as exc:  # noqa: BLE001 - never 500 the runtime; report cleanly
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "timestamp": datetime.now().isoformat(),
        }

    is_error = bool(result.get("error"))
    return {
        "status": "error" if is_error else "success",
        "result": result,
        "markdown": None if is_error else _markdown.render(result),
        "timestamp": datetime.now().isoformat(),
    }


@app.ping
def health_check() -> PingStatus:
    """GET /health — readiness probe AgentBase polls to mark the runtime ACTIVE.

    Confirms the agent can construct its core (dependency container + use-case and
    connector discovery). Deliberately does NOT call the LLM or external APIs — a
    transient network/LLM issue must not flip the runtime out of ACTIVE. If the
    core cannot build (broken import/config), the exception propagates and the
    runtime correctly sees the agent as unhealthy.
    """
    _router_instance()  # builds once and caches; raises only if the agent is broken
    return PingStatus.HEALTHY


# In-process scheduler — ON by default (set ENABLE_SCHEDULER=0 to disable): a daemon
# thread runs the UC9 watch — user subscriptions + the env watchlist — on a timer,
# delivering alerts at their scheduled hour without an external cron. Started at import
# so it runs both under `python main.py` and when the platform imports `app`; wrapped
# so it can never block boot/health.
try:
    from scheduler.watch import start_background_scheduler
    start_background_scheduler(_router_instance().deps)
except Exception as _exc:  # noqa: BLE001 - the scheduler must never block boot/health
    import logging
    logging.getLogger("main").warning("in-process scheduler not started: %s", _exc)


if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 8080)), host="0.0.0.0")
