"""Durable trip progress and cooperative turn cancellation/deadlines (INT-416/417).

Each conversation thread has one turn record in the existing `settings` table, so it works on
SQLite and Postgres without a schema change. Leg progress is derived from the saved requests,
leg metadata and snapshots that the workflow already writes; pending approval comes from the
agent checkpoint. Nothing here calls a model or provider.

Cancellation is cooperative: a running turn stops at its next model or tool boundary, while
waiting for browser admission, or immediately before the Generate click. A click already in
flight is never interrupted or repeated; its outcome is saved as generated or uncertain.
"""

import json
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from langchain.agents.middleware import AgentMiddleware

from ifdispatcher import core
from ifdispatcher.config import setting

BOOT_ID = uuid.uuid4().hex  # identifies this server process; other values mean a restart
PREFIX = "turn_progress:"
LIVE = {"queued", "running"}
# A Generate claim older than one bounded browser workflow cannot still be in progress.
GENERATION_SETTLE_SECONDS = 180 + 8 * 3 + 12


def turn_deadline_seconds() -> float:
    """Wall-clock budget for one plan_flight/approve_dispatch turn (operational setting)."""
    return float(setting("IFD_TURN_DEADLINE_SECONDS") or 600)


class TurnCancelled(Exception):
    """Stops the current turn at a safe boundary. Not a ValueError, so tools do not absorb it."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class TurnControl:
    def __init__(self, thread_id: str, deadline_seconds: float):
        self.thread_id = thread_id
        self.deadline = time.monotonic() + deadline_seconds
        self.event = threading.Event()
        self.reason = None

    def cancel(self, reason: str):
        self.reason = self.reason or reason
        self.event.set()

    def check(self):
        if self.event.is_set():
            raise TurnCancelled(self.reason or "cancelled")
        if time.monotonic() >= self.deadline:
            self.cancel("deadline_exceeded")
            raise TurnCancelled("deadline_exceeded")


_control: ContextVar[TurnControl | None] = ContextVar("ifd_turn_control", default=None)


def check() -> None:
    """Raise TurnCancelled if this turn was cancelled or passed its deadline; else no-op."""
    control = _control.get()
    if control is not None:
        control.check()


def bind(control: TurnControl):
    return _control.set(control)


def unbind(token) -> None:
    _control.reset(token)


class TurnControlMiddleware(AgentMiddleware):
    """Check cancellation/deadline before every model call and tool call of a turn."""

    def before_model(self, state, runtime):
        check()

    async def abefore_model(self, state, runtime):
        check()

    def wrap_tool_call(self, request, handler):
        check()
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        check()
        return await handler(request)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def update(thread_id: str, change) -> dict:
    """Atomically read-modify-write a thread's turn record; returns the new record."""
    with core.open_store().connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT value FROM settings WHERE name=?", (PREFIX + thread_id,)
        ).fetchone()
        record = json.loads(row[0]) if row else {"thread_id": thread_id, "approvals": []}
        change(record)
        record["updated_at"] = _now()
        db.execute(
            "INSERT INTO settings (name,value) VALUES (?,?) "
            "ON CONFLICT (name) DO UPDATE SET value=excluded.value",
            (PREFIX + thread_id, json.dumps(record)),
        )
        return record


def read(thread_id: str) -> dict | None:
    raw = core.open_store().read_setting(PREFIX + thread_id)
    return json.loads(raw) if raw else None


def start_turn(thread_id: str, action: str) -> dict:
    deadline = turn_deadline_seconds()

    def change(record):
        record.update(
            turn_id=uuid.uuid4().hex,
            action=action,
            status="queued",
            boot_id=BOOT_ID,
            started_at=_now(),
            deadline_seconds=deadline,
            deadline_at=(datetime.now(timezone.utc) + timedelta(seconds=deadline)).isoformat(),
            cancel=None,
            error=None,
        )

    return update(thread_id, change)


def set_status(thread_id: str, status: str, **fields) -> dict:
    return update(thread_id, lambda record: record.update(status=status, **fields))


def finish_turn(
    thread_id: str,
    status: str,
    active_seconds: float,
    cancel_outcome: str | None = None,
    cancelled_interrupt: str | None = None,
    **fields,
) -> dict:
    """Record a turn's terminal status and its active execution time.

    Only time inside a turn counts; waiting for a human approval happens between turns, so it
    is excluded from `active_seconds_total` by construction.
    """

    def change(record):
        record.update(status=status, finished_at=_now(), **fields)
        record["active_seconds"] = round(active_seconds, 3)
        record["active_seconds_total"] = round(
            (record.get("active_seconds_total") or 0) + active_seconds, 3
        )
        if cancel_outcome and record.get("cancel"):
            # requested -> stopped (at a safe point) or completed (finished before a boundary)
            record["cancel"]["outcome"] = cancel_outcome
            record["cancel"]["confirmed_at"] = _now()
        if cancelled_interrupt:
            record["cancelled_interrupt"] = cancelled_interrupt

    return update(thread_id, change)


def turn_view(record: dict | None, live: bool) -> dict | None:
    """The persisted turn, with work left behind by a restart reported as interrupted."""
    if record is None:
        return None
    view = {
        k: record.get(k)
        for k in (
            "turn_id",
            "action",
            "status",
            "started_at",
            "deadline_at",
            "finished_at",
            "updated_at",
            "active_seconds",
            "active_seconds_total",
            "cancel",
            "error",
        )
    }
    if record.get("status") in LIVE and not live:
        view["status"] = "interrupted"
        view["interrupted_reason"] = (
            "server_restarted" if record.get("boot_id") != BOOT_ID else "turn_not_running"
        )
    return view


def leg_stage(meta: dict, snapshot: bool, turn_live: bool = True) -> str:
    """One leg revision's durable stage, derived only from saved records."""
    generation = meta.get("generation") or {}
    status = generation.get("status")
    if meta.get("briefing"):
        return "infeasible" if meta.get("task_outcome") == "infeasible" else "briefing_ready"
    if snapshot:
        return "plan_retained"
    if status == "generated":
        return "generated_awaiting_finalize"
    if status == "uncertain":
        return "generation_uncertain"
    if status == "clicking":
        try:
            age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(generation["at"])
            ).total_seconds()
        except (KeyError, TypeError, ValueError):
            age = GENERATION_SETTLE_SECONDS
        return (
            "generating"
            if turn_live and age < GENERATION_SETTLE_SECONDS
            else ("generation_uncertain")
        )
    if meta.get("cancelled") or status == "cancelled":
        return "cancelled"
    if status:
        return "generation_failed"
    return "awaiting_generation"


COMPLETED = {"briefing_ready", "infeasible", "plan_retained"}


def trips_in(state) -> list[str]:
    """Trip ids this conversation dispatched or is asking to dispatch, in first-use order."""
    found = []
    values = getattr(state, "values", None) or {}
    calls = [c for m in values.get("messages", []) for c in (getattr(m, "tool_calls", None) or [])]
    for interrupt in getattr(state, "interrupts", None) or ():
        calls += interrupt.value.get("action_requests", [])
    for call in calls:
        trip = (call.get("args") or {}).get("trip")
        if isinstance(trip, str) and trip not in found:
            found.append(trip)
    return found


def legs(trip: str, turn_live: bool = True) -> list[dict]:
    store = core.open_store()
    result = []
    for leg, request, meta in store.trip_legs(trip):
        try:
            snap = store.read(trip, leg, request["revision"])
        except ValueError:
            snap = None
        generation = meta.get("generation") or {}
        stage = leg_stage(meta, bool(snap), turn_live)
        result.append(
            {
                "trip": trip,
                "leg": leg,
                "revision": request["revision"],
                "stage": stage,
                "approval": "approved",  # a saved request exists only after exact approval
                "completed": stage in COMPLETED,
                "uncertain": stage == "generation_uncertain",
                "generation": {k: generation.get(k) for k in ("status", "clicked", "at")},
                "cancelled": meta.get("cancelled"),
                "snapshot_sha256": snap["raw_sha256"] if snap else None,
            }
        )
    return result


def pending_approval(state, record: dict | None) -> dict | None:
    interrupts = getattr(state, "interrupts", None) or ()
    if not interrupts:
        return None
    request = interrupts[0].value["action_requests"][0]
    interrupt_id = getattr(interrupts[0], "id", None)
    cancelled = bool(record and interrupt_id and record.get("cancelled_interrupt") == interrupt_id)
    return {
        "status": "cancelled" if cancelled else "pending",
        "interrupt_id": interrupt_id,
        "action": request["name"],
        "inputs": request["args"],
    }


def snapshot(thread_id: str, state, live: bool) -> dict:
    """Whole-conversation progress for MCP clients; reads storage and checkpoint only."""
    record = read(thread_id)
    turn = turn_view(record, live)
    if not getattr(state, "values", None) and record is None:
        return {"status": "not_found", "thread_id": thread_id}
    turn_live = bool(turn and turn["status"] in LIVE)
    trips = [{"trip": trip, "legs": legs(trip, turn_live)} for trip in trips_in(state)]
    all_legs = [leg for trip in trips for leg in trip["legs"]]
    approval = pending_approval(state, record)
    return {
        "status": "ok",
        "thread_id": thread_id,
        "turn": turn,
        "approval": {"pending": approval, "history": (record or {}).get("approvals", [])},
        "trips": trips,
        "completed_legs": [_ident(leg) for leg in all_legs if leg["completed"]],
        "uncertain_generations": [_ident(leg) for leg in all_legs if leg["uncertain"]],
        "interrupted": bool(turn and turn["status"] == "interrupted"),
        "next": _next(turn, approval, all_legs),
    }


def _ident(leg: dict) -> dict:
    return {k: leg[k] for k in ("trip", "leg", "revision", "stage")}


UNCERTAIN_NEXT = (
    "Generate was clicked but completion was not observed. Do not generate this revision again. "
    "Check SimBrief; if the plan exists, ask the dispatcher to finalize it, otherwise ask for a "
    "new approved revision."
)


def _next(turn, approval, all_legs) -> str:
    if turn and turn["status"] in LIVE:
        return "Work is still running. Call turn_status, or cancel_trip to stop it."
    if any(leg["uncertain"] for leg in all_legs):
        return UNCERTAIN_NEXT
    if approval and approval["status"] == "pending":
        return "Show the pending inputs to the user, then call approve_dispatch with their answer."
    if any(leg["stage"] == "cancelled" for leg in all_legs):
        return (
            "Cancelled revisions were never generated and their approval was withdrawn. To "
            "continue one, ask the user and request a new approved revision with plan_flight."
        )
    if turn and turn["status"] == "interrupted":
        return (
            "The previous turn stopped when the server restarted. Completed legs are kept. Send "
            "plan_flight on this thread to continue; do not repeat a generation shown above."
        )
    return "Continue with plan_flight on this thread, or read briefings with list_saved_trips."


def mark_cancelled_legs(trips: list[str], thread_id: str, reason: str) -> list[dict]:
    """Withdraw approval for approved revisions whose Generate was never clicked.

    Completed plans, generated or uncertain revisions are left untouched. A cancelled revision
    can only proceed through a new approved revision.
    """
    store = core.open_store()
    marked = []
    for trip in trips:
        for leg, request, _ in store.trip_legs(trip):
            revision = request["revision"]
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT payload FROM leg_meta WHERE trip=? AND leg=? AND revision=?",
                    (trip, leg, revision),
                ).fetchone()
                meta = json.loads(row[0]) if row else {}
                snap = db.execute(
                    "SELECT 1 FROM snapshots WHERE trip=? AND leg=? AND revision=?",
                    (trip, leg, revision),
                ).fetchone()
                generation = meta.get("generation") or {}
                if (
                    snap
                    or meta.get("briefing")
                    or meta.get("cancelled")
                    or generation.get("at")
                    or generation.get("status") in ("clicking", "generated", "uncertain")
                ):
                    continue
                meta["cancelled"] = {"at": _now(), "thread_id": thread_id, "reason": reason}
                db.execute(
                    "INSERT OR REPLACE INTO leg_meta VALUES (?,?,?,?)",
                    (trip, leg, revision, core.encode(meta)),
                )
            marked.append({"trip": trip, "leg": leg, "revision": revision})
    return marked
