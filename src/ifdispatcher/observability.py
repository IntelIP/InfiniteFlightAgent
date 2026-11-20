"""Per-turn provider measurements and objective workflow signals; never a claim of user acceptance."""

import json
import logging
import time
from contextvars import ContextVar

meter = ContextVar("ifd_provider_events", default=None)
log = logging.getLogger(__name__)
PRODUCT = "jumpseat"
_trace_home: dict = {}  # LangSmith web URL prefix, looked up once per process
LOOKUP_RETRY_SECONDS = 300.0  # after a failed lookup, links carry only the run id until then


def environment() -> str:
    """Deployment environment for trace metadata; the Worker sets production."""
    from ifdispatcher.config import setting

    return setting("IFD_ENVIRONMENT") or "local"


def run_metadata(surface: str) -> dict:
    """Standard root-run metadata; LangGraph adds thread_id from the config."""
    from ifdispatcher import __version__

    return {
        "product": PRODUCT,
        "version": __version__,
        "environment": environment(),
        "surface": surface,
    }


def _tracing_key() -> str | None:
    from ifdispatcher.config import setting

    key = setting("LANGSMITH_API_KEY")
    return key if key and (setting("LANGSMITH_TRACING") or "").lower() == "true" else None


def trace_link(run_id: str) -> dict | None:
    """The turn's LangSmith root run and a one-click URL; None when tracing is off.

    The URL needs the workspace and project ids, read once from LangSmith. If that lookup
    fails the run id is still returned, so the trace can be found by id, and the lookup is
    retried only after LOOKUP_RETRY_SECONDS.
    """
    key = _tracing_key()
    if not key:
        return None
    if "prefix" not in _trace_home and time.monotonic() >= _trace_home.get("retry_at", 0.0):
        try:
            from langsmith import Client, utils
            from ifdispatcher.config import setting

            client = Client(api_key=key)
            project = client.read_project(project_name=setting("LANGSMITH_PROJECT") or "default")
            host = utils.get_host_url(None, client.api_url)
            _trace_home["prefix"] = f"{host}/o/{project.tenant_id}/projects/p/{project.id}/r/"
        except Exception as exc:
            # Back off so a LangSmith outage cannot make every turn wait on the lookup again.
            _trace_home["retry_at"] = time.monotonic() + LOOKUP_RETRY_SECONDS
            log.warning("LangSmith project lookup unavailable: %s", type(exc).__name__)
    prefix = _trace_home.get("prefix")
    return {
        "run_id": run_id,
        "url": f"{prefix}{run_id}?trace_id={run_id}" if prefix else None,
    }


def event(provider: str, **fields):
    events = meter.get()
    entry = {"provider": provider, **fields}
    if events is not None:
        events.append(entry)
    return entry


def browser_opened(session_id: str):
    event("browserbase", session_id=session_id, opened_monotonic=time.monotonic(), cost_usd=None)


def browser_closed(session_id: str, confirmed: bool = True, requested: bool = True):
    for entry in meter.get() or []:
        if entry.get("session_id") == session_id and "opened_monotonic" in entry:
            entry["elapsed_s"] = round(time.monotonic() - entry.pop("opened_monotonic"), 3)
            entry["release_requested"] = requested
            entry["released"] = confirmed
            entry["minimum_billable_minutes_estimate"] = max(1, entry["elapsed_s"] / 60)


def summarize(messages, seen: set) -> dict:
    results = []
    for message in messages:
        if message.type != "tool" or message.id in seen:
            continue
        try:
            data = json.loads(message.content)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        results.append(
            {
                "tool": message.name,
                "status": data.get("status"),
                "retryable": data.get("retryable"),
                "task_outcome": data.get("task_outcome"),
            }
        )
    blocked = [
        r
        for r in results
        if r["status"]
        in (
            "error",
            "fill_mismatch",
            "stale_plan",
            "plan_mismatch",
            "not_logged_in",
            "needs_review",
            "uncertain",
            "browser_limited",
            "queue_full",
        )
    ]
    infeasible = any(r["task_outcome"] == "infeasible" for r in results)
    ready = any(r["task_outcome"] == "briefing_ready" for r in results)
    return {
        "tool_results": results,
        "blocked_steps": len(blocked),
        "recoverable_steps": sum(r["retryable"] is True for r in blocked),
        "outcome": "infeasible"
        if infeasible
        else "briefing_ready"
        if ready
        else "blocked"
        if blocked
        else "conversation",
        "user_task_completed": None,
        "note": "Workflow signals only. User acceptance and semantic correctness require review.",
    }


def write_feedback(run_id: str, signals: dict):
    """Best-effort objective feedback on the root trace; a tracing outage cannot fail a flight."""
    key = _tracing_key()
    if not key:
        return
    try:
        from langsmith import Client

        client = Client(api_key=key)
        client.create_feedback(
            run_id,
            key="ifd_workflow_outcome",
            value=signals["outcome"],
            comment="Automatic workflow signal, not user acceptance",
            extend_trace_retention=False,
        )
        client.create_feedback(
            run_id,
            key="ifd_blocked_steps",
            score=signals["blocked_steps"],
            extend_trace_retention=False,
        )
    except Exception as exc:
        log.warning("LangSmith feedback unavailable: %s", type(exc).__name__)
