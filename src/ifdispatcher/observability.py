"""Per-turn provider measurements and objective workflow signals; never a claim of user acceptance."""

import json
import logging
import time
from contextvars import ContextVar

meter = ContextVar("ifd_provider_events", default=None)
log = logging.getLogger(__name__)


def event(provider: str, **fields):
    events = meter.get()
    entry = {"provider": provider, **fields}
    if events is not None:
        events.append(entry)
    return entry


def browser_opened(session_id: str):
    event("browserbase", session_id=session_id, opened_monotonic=time.monotonic(), cost_usd=None)


def browser_closed(session_id: str):
    for entry in meter.get() or []:
        if entry.get("session_id") == session_id and "opened_monotonic" in entry:
            entry["elapsed_s"] = round(time.monotonic() - entry.pop("opened_monotonic"), 3)
            entry["released"] = True


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
    from ifdispatcher.config import setting

    key = setting("LANGSMITH_API_KEY")
    if not key or (setting("LANGSMITH_TRACING") or "").lower() != "true":
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
