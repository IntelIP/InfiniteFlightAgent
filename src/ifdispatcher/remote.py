"""Remote MCP server for the deployed dispatcher (Streamable HTTP on :8080).

Runs in the Cloudflare Container behind the Worker. Cloudflare Access authenticates the user;
the Worker adds X-IFD-Internal-Token, which this server requires on every request except
/health. Conversations persist per thread_id in the checkpointer (Neon in deployment).

Agent turns run in a background thread so a long turn (SimBrief generation takes about two
minutes) does not hold the MCP call open past client timeouts: a tool waits up to
WAIT_SECONDS, then returns status "running" and the client polls turn_status.
"""

import asyncio
import hmac
import os
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from langgraph.types import Command
from starlette.requests import Request
from starlette.responses import JSONResponse

from ifdispatcher import __version__
from ifdispatcher.config import export_tracing_settings, paid_operations_enabled, setting
from ifdispatcher import observability, operations, progress, simbrief_browser

TOKEN_HEADER = "x-ifd-internal-token"
WAIT_SECONDS = 25
MAX_OUTSTANDING_TURNS = 6  # four workers and at most two waiting turns
_agent = None
_turns: dict[str, Future] = {}  # latest turn per thread_id
_controls: dict[str, progress.TurnControl] = {}  # cancellation/deadline of that turn
_pool = ThreadPoolExecutor(max_workers=4)


def _get_agent():
    global _agent
    if _agent is None:
        from ifdispatcher.agent import build_agent, checkpointer

        _agent = build_agent(checkpointer=checkpointer())
    return _agent


mcp = FastMCP(
    "InfiniteFlightDispatcher",
    stateless_http=True,
    # Host checks are replaced by the internal token: only the Worker can reach this server.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _turn(result, thread_id: str, seen: set) -> dict[str, Any]:
    if result.interrupts:
        from ifdispatcher.agent import new_briefings

        request = result.interrupts[0].value["action_requests"][0]
        turn = {
            "status": "approval_required",
            "thread_id": thread_id,
            "action": request["name"],
            "inputs": request["args"],
            "summary": request["description"],
            "next": "Show the summary to the user, then call approve_dispatch with their answer.",
        }
        briefings = new_briefings(result.value["messages"], seen)
        if briefings:
            turn["briefings"] = briefings
            turn["next"] = (
                "Show these finished briefings first, then the summary, then call "
                "approve_dispatch with the user's answer."
            )
        return turn
    return {"status": "reply", "thread_id": thread_id, "reply": result.value["messages"][-1].text}


def _live(thread_id: str) -> bool:
    turn = _turns.get(thread_id)
    return bool(turn and not turn.done())


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _run(payload, thread_id: str, control: progress.TurnControl | None = None) -> dict[str, Any]:
    control = control or progress.TurnControl(thread_id, progress.turn_deadline_seconds())
    bound = progress.bind(control)
    started = time.monotonic()
    try:
        control.check()  # cancelled while queued: start no work
        progress.set_status(thread_id, "running")
        response = _invoke(payload, thread_id)
        if response["status"] == "approval_required" and control.event.is_set():
            # Cancel arrived while the model proposed this dispatch: withdraw it, never offer it.
            raise progress.TurnCancelled(control.reason or "cancelled")
        progress.finish_turn(
            thread_id,
            response["status"],
            time.monotonic() - started,
            cancel_outcome="completed" if control.event.is_set() else None,
        )
        return response
    except progress.TurnCancelled as exc:
        state = _get_agent().get_state(_config(thread_id))
        pending = progress.pending_approval(state, None)
        progress.finish_turn(
            thread_id,
            "deadline_exceeded" if exc.reason == "deadline_exceeded" else "cancelled",
            time.monotonic() - started,
            cancel_outcome="stopped",
            cancelled_interrupt=pending["interrupt_id"] if pending else None,
        )
        # A dispatch saved after cancel_trip looked (or before a deadline) needs a new approval.
        progress.mark_cancelled_legs(progress.trips_in(state), thread_id, exc.reason)
        report = progress.snapshot(thread_id, state, False)
        return {
            "status": "cancelled",
            "thread_id": thread_id,
            "reason": exc.reason,
            "progress": report,
            "next": "Work stopped at a safe point; completed legs are kept. " + report["next"],
        }
    except Exception as exc:
        progress.finish_turn(
            thread_id, "failed", time.monotonic() - started, error=type(exc).__name__
        )
        raise
    finally:
        progress.unbind(bound)


def _invoke(payload, thread_id: str) -> dict[str, Any]:
    if not paid_operations_enabled():
        return {"status": "paid_operations_disabled", "thread_id": thread_id}
    from ifdispatcher.agent import message_ids

    run_id = str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": thread_id},
        "tags": ["remote", f"v{__version__}"],
        "run_id": run_id,
        "metadata": {"version": __version__, "surface": "remote"},
    }
    agent = _get_agent()
    seen = message_ids(agent.get_state(config))
    events = []
    token = observability.meter.set(events)
    try:
        with simbrief_browser.session_scope():
            result = agent.invoke(payload, config=config, version="v2")
        response = _turn(result, thread_id, seen)
        signals = observability.summarize(result.value["messages"], seen)
        if result.interrupts:
            signals["outcome"] = "approval_required"
        response.update(run_id=run_id, workflow=signals, provider_usage=events)
        observability.write_feedback(run_id, signals)
        return response
    finally:
        observability.meter.reset(token)


async def _wait(thread_id: str) -> dict[str, Any]:
    turn = _turns[thread_id]
    try:
        # shield: a timeout must not cancel the turn itself.
        return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(turn)), WAIT_SECONDS)
    except TimeoutError:
        return {
            "status": "running",
            "thread_id": thread_id,
            "next": "Still working. Call turn_status with this thread_id in about 20 seconds.",
        }


async def _start(payload, thread_id: str, action: str) -> dict[str, Any]:
    running = _turns.get(thread_id)
    if running and not running.done():
        return {
            "status": "busy",
            "thread_id": thread_id,
            "next": "A turn is still running on this thread. Call turn_status instead.",
        }
    if sum(not f.done() for f in _turns.values()) >= MAX_OUTSTANDING_TURNS:
        return {
            "status": "queue_full",
            "thread_id": thread_id,
            "next": "Dispatcher busy; try later. No work was started.",
        }
    record = progress.start_turn(thread_id, action)
    control = progress.TurnControl(thread_id, record["deadline_seconds"])
    _controls[thread_id] = control
    _turns[thread_id] = _pool.submit(_run, payload, thread_id, control)
    return await _wait(thread_id)


@mcp.tool()
async def plan_flight(message: str, thread_id: str | None = None) -> dict[str, Any]:
    """Send the user's message to the Infinite Flight dispatcher and return its reply.

    Start a conversation without thread_id; pass the returned thread_id on every later message
    of the same trip. Relay the reply to the user as written. If the status is
    approval_required, show any "briefings" (legs already finished) and then the summary, and ask
    the user before calling approve_dispatch. If the status is running, call turn_status with the
    thread_id until it returns the reply.
    """
    thread_id = thread_id or f"trip-{uuid.uuid4().hex[:10]}"
    payload = {"messages": [{"role": "user", "content": message}]}
    return await _start(payload, thread_id, "plan_flight")


@mcp.tool()
async def approve_dispatch(
    thread_id: str, approve: bool, note: str | None = None
) -> dict[str, Any]:
    """Answer a pending approval for thread_id. approve=true prepares and generates the SimBrief
    plan (about two minutes, so this usually returns status running; poll turn_status) and
    then returns the briefing; approve=false declines with the user's note. Only call after the
    user explicitly answered.
    """
    if not _live(thread_id):
        state = _get_agent().get_state(_config(thread_id))
        pending = progress.pending_approval(state, progress.read(thread_id))
        if pending and pending["status"] == "cancelled" and approve:
            return {
                "status": "cancelled",
                "thread_id": thread_id,
                "pending": pending,
                "next": "This approval was cancelled and cannot be approved. Nothing was "
                "dispatched or generated. Send plan_flight to start again with a new approval.",
            }
        if pending:
            entry = {
                "interrupt_id": pending["interrupt_id"],
                "action": pending["action"],
                **{
                    k: pending["inputs"].get(k)
                    for k in ("trip", "leg", "revision", "base_revision")
                },
                "decision": "approve" if approve else "reject",
                "at": progress._now(),
            }
            progress.update(thread_id, lambda r: r.setdefault("approvals", []).append(entry))
    decision = {"type": "approve"} if approve else {"type": "reject", "message": note or "declined"}
    payload = Command(resume={"decisions": [decision]})
    return await _start(payload, thread_id, "approve_dispatch")


@mcp.tool()
async def turn_status(thread_id: str) -> dict[str, Any]:
    """Result of the latest plan_flight or approve_dispatch call on thread_id after it returned
    status running. Returns running again (call later), or the reply / approval request.
    """
    finished = thread_id in _turns and _turns[thread_id].done()
    record = progress.read(thread_id) if finished or thread_id not in _turns else None
    if finished and record and record.get("status") == "cancelled":
        # The cached result predates cancel_trip (e.g. a withdrawn approval_required);
        # report the cancellation instead of asking for an approval that is refused.
        return {
            "status": "cancelled",
            "thread_id": thread_id,
            "turn": progress.turn_view(record, live=False),
            "next": "This turn was cancelled; any pending approval was withdrawn and cannot be "
            "approved. Call trip_progress for kept legs, or send plan_flight to start again.",
        }
    if thread_id not in _turns:
        turn = progress.turn_view(record, live=False)
        if turn:
            return {
                "status": turn["status"],
                "thread_id": thread_id,
                "turn": turn,
                "next": "Call trip_progress for completed legs, pending approval and any "
                "uncertain generation before continuing with plan_flight on this thread.",
            }
        return {
            "status": "not_found",
            "thread_id": thread_id,
            "next": "No turn on this thread since the server started. If one was running, the "
            "server restarted; send plan_flight on this thread to ask where it stands.",
        }
    return await _wait(thread_id)


@mcp.tool()
def trip_progress(thread_id: str) -> dict:
    """Durable progress of a conversation without invoking the model or any provider.

    Returns the current turn (running, approval_required, reply, cancelled, deadline_exceeded,
    failed, or interrupted by a restart), the pending or cancelled approval, and each dispatched
    leg's stage: awaiting_generation, generating, generated_awaiting_finalize,
    generation_uncertain, generation_failed, cancelled, plan_retained, briefing_ready or
    infeasible. Never retry a generation_uncertain leg.
    """
    state = _get_agent().get_state(_config(thread_id))
    return progress.snapshot(thread_id, state, _live(thread_id))


@mcp.tool()
async def cancel_trip(thread_id: str, reason: str | None = None) -> dict:
    """Stop this conversation's queued or running work and withdraw a pending approval.

    Only call when the user asks to stop. Completed plans and briefings are kept. Approved
    revisions not yet generated need a new approval to continue. A Generate click already in
    progress cannot be undone or repeated; it is reported as generated or uncertain.
    """
    state = _get_agent().get_state(_config(thread_id))
    record = progress.read(thread_id)
    if not state.values and record is None:
        return {"status": "not_found", "thread_id": thread_id}
    reason = reason or "cancelled_by_user"
    running = _live(thread_id)
    pending = progress.pending_approval(state, record)

    def change(r):
        r["cancel"] = {
            "requested_at": progress._now(),
            "reason": reason,
            "while": "running" if running else "approval_pending" if pending else "idle",
        }
        if pending:
            r["cancelled_interrupt"] = pending["interrupt_id"]
        if not running:
            # Nothing is executing, so the request is confirmed immediately.
            r["cancel"].update(outcome="stopped", confirmed_at=r["cancel"]["requested_at"])
            r["status"] = "cancelled"

    # Persist the request before signalling, so the turn's terminal record can confirm it.
    progress.update(thread_id, change)
    if running:
        _controls[thread_id].cancel(reason)
    withdrawn = progress.mark_cancelled_legs(progress.trips_in(state), thread_id, reason)
    if running:
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(_turns[thread_id])), WAIT_SECONDS
            )
        except Exception:
            pass  # timeout: still finishing; a turn's own failure is recorded in its progress
    live = _live(thread_id)
    state = _get_agent().get_state(_config(thread_id))
    if running and not live:
        # The turn may have finished before seeing the signal: confirm the request as
        # completed, and still withdraw any approval or unclicked revision it left behind.
        late = progress.pending_approval(state, None)

        def settle(r):
            if r.get("cancel"):
                r["cancel"].setdefault("outcome", "completed")
                r["cancel"].setdefault("confirmed_at", progress._now())
            if late:
                r["cancelled_interrupt"] = late["interrupt_id"]

        progress.update(thread_id, settle)
        pending = pending or late
        withdrawn += progress.mark_cancelled_legs(progress.trips_in(state), thread_id, reason)
    report = progress.snapshot(thread_id, state, live)
    return {
        "status": "cancelling" if live else "cancelled",
        "thread_id": thread_id,
        "stopped_running_turn": running,
        # stopped (at a safe point) or completed (finished first); None while still cancelling
        "outcome": ((report.get("turn") or {}).get("cancel") or {}).get("outcome"),
        "withdrawn_approval": pending if pending else None,
        "withdrawn_revisions": withdrawn,
        "progress": report,
        "next": ("A Generate click may be finishing; call trip_progress shortly. " if live else "")
        + report["next"],
    }


@mcp.tool()
def browser_status() -> dict:
    """Inspect browser admission and active provider sessions without opening a browser."""
    return simbrief_browser.session_inventory()


@mcp.tool()
def list_saved_trips(trip: str | None = None) -> dict:
    """List saved trip ids, or read a trip's latest legs and briefings without model/provider calls."""
    return operations.saved_trips(trip)


@mcp.tool()
def conversation_status(thread_id: str) -> dict:
    """Read a persisted conversation after a restart without invoking the model or generating.

    Pass the original conversation thread_id; this differs from a saved trip id.
    """
    state = _get_agent().get_state({"configurable": {"thread_id": thread_id}})
    if not state.values:
        return {"status": "not_found", "thread_id": thread_id}
    pending = progress.pending_approval(state, progress.read(thread_id))
    if pending and pending["status"] == "cancelled":
        return {
            "status": "approval_cancelled",
            "thread_id": thread_id,
            "inputs": pending["inputs"],
            "next": "The owner cancelled this approval; it cannot be approved. Call trip_progress "
            "for kept legs, or send plan_flight on this thread to start again.",
        }
    if state.interrupts:
        request = state.interrupts[0].value["action_requests"][0]
        return {
            "status": "approval_required",
            "thread_id": thread_id,
            "summary": request["description"],
            "inputs": request["args"],
        }
    messages = state.values.get("messages", [])
    reply = next((m.text for m in reversed(messages) if m.type == "ai" and m.text), None)
    return {
        "status": "saved",
        "thread_id": thread_id,
        "reply": reply,
        "next": "Continue with plan_flight using this same thread_id. Check saved trip status before retrying interrupted generation.",
    }


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "paid_operations_enabled": paid_operations_enabled(),
            "database": bool(setting("DATABASE_URL")),
        }
    )


@mcp.custom_route("/internal/simbrief/keepalive", methods=["POST"])
async def simbrief_keepalive(_: Request) -> JSONResponse:
    """The old cron is a no-op: actual browser work signs in on demand."""
    if not paid_operations_enabled():
        return JSONResponse({"status": "paid_operations_disabled"})
    return JSONResponse({"status": "skipped", "reason": "SimBrief login refreshed on demand"})


def create_app():
    app = mcp.streamable_http_app()
    expected = setting("IFD_INTERNAL_TOKEN") or ""

    async def gate(scope, receive, send):
        if scope["type"] == "http" and scope["path"] != "/health":
            headers = dict(scope.get("headers") or [])
            given = headers.get(TOKEN_HEADER.encode(), b"").decode()
            if not expected or not hmac.compare_digest(given, expected):
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await app(scope, receive, send)

    return gate


def main() -> None:
    import uvicorn

    export_tracing_settings()
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
