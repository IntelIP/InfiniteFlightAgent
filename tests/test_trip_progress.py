"""INT-416/417: durable trip progress, cancellation and deadlines (no model/provider calls)."""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ifdispatcher import browser_budget, core, progress, remote, workflow
from ifdispatcher.core import Dispatch

DEPARTURE = "2026-11-08T12:00:00Z"


@pytest.fixture
def store():
    return core.open_store()


def prepare(store, trip="T1", leg="1", revision=1):
    store.prepare(
        Dispatch(
            trip=trip,
            leg=leg,
            revision=revision,
            origin="KIAD",
            destination="KEWR",
            aircraft="A20N",
            departure=DEPARTURE,
            units="KGS",
            passengers=4,
        )
    )
    store.save_meta(trip, leg, revision, {"prepared_at": DEPARTURE})


@pytest.fixture
def bound():
    """A turn control bound to the current context, as remote._run does."""
    control = progress.TurnControl("thread-1", 60)
    token = progress.bind(control)
    yield control
    progress.unbind(token)


def test_browser_limits_unchanged():
    assert (
        browser_budget.SESSION_SECONDS,
        browser_budget.IDLE_SECONDS,
        browser_budget.QUEUE_SECONDS,
        browser_budget.MAX_WAITERS,
    ) == (180, 30, 30, 2)


@pytest.mark.parametrize(
    "meta,snapshot,live,stage",
    [
        ({}, False, True, "awaiting_generation"),
        ({"generation": {"status": "fill_mismatch"}}, False, True, "generation_failed"),
        ({"cancelled": {"reason": "x"}}, False, True, "cancelled"),
        ({"generation": {"status": "cancelled"}, "cancelled": {}}, False, True, "cancelled"),
        ({"generation": {"status": "generated"}}, False, True, "generated_awaiting_finalize"),
        ({"generation": {"status": "uncertain"}}, False, True, "generation_uncertain"),
        ({"generation": {"status": "generated"}}, True, True, "plan_retained"),
        ({"briefing": "**SPAWN:**"}, True, True, "briefing_ready"),
        ({"briefing": "x", "task_outcome": "infeasible"}, True, True, "infeasible"),
    ],
)
def test_leg_stage_from_saved_records(meta, snapshot, live, stage):
    assert progress.leg_stage(meta, snapshot, live) == stage


def test_click_in_progress_becomes_uncertain_when_not_live_or_too_old():
    now = datetime.now(timezone.utc)
    recent = {"generation": {"status": "clicking", "at": now.isoformat()}}
    old = {"generation": {"status": "clicking", "at": (now - timedelta(minutes=10)).isoformat()}}
    assert progress.leg_stage(recent, False, turn_live=True) == "generating"
    assert progress.leg_stage(recent, False, turn_live=False) == "generation_uncertain"
    assert progress.leg_stage(old, False, turn_live=True) == "generation_uncertain"


def test_check_is_noop_without_a_turn_and_honors_cancel_and_deadline():
    progress.check()
    control = progress.TurnControl("t", 60)
    token = progress.bind(control)
    try:
        progress.check()
        control.cancel("owner")
        with pytest.raises(progress.TurnCancelled, match="owner"):
            progress.check()
    finally:
        progress.unbind(token)
    expired = progress.TurnControl("t", 0)
    with pytest.raises(progress.TurnCancelled, match="deadline_exceeded"):
        expired.check()


def test_middleware_stops_before_model_and_tool(bound):
    middleware = progress.TurnControlMiddleware()
    called = []
    assert middleware.wrap_tool_call("request", lambda r: called.append(r) or "ok") == "ok"
    bound.cancel("owner")
    with pytest.raises(progress.TurnCancelled):
        middleware.before_model({}, None)
    with pytest.raises(progress.TurnCancelled):
        middleware.wrap_tool_call("request", lambda r: called.append(r))
    assert called == ["request"]


def generation_stub(monkeypatch, clicks, after_click=None):
    def generate(fields, click, shots_dir, before_click=None):
        before_click()
        clicks.append(fields["tag"])
        if after_click:
            after_click()
        return {"status": "generated", "session": "controlled"}

    monkeypatch.setattr(workflow.simbrief_browser, "generate", generate)
    monkeypatch.setattr(workflow.artifacts, "upload", lambda *a, **k: [])


def test_cancel_before_click_never_clicks_and_withdraws_revision(store, bound, monkeypatch):
    prepare(store)
    clicks = []
    generation_stub(monkeypatch, clicks)
    bound.cancel("owner cancelled")
    with pytest.raises(progress.TurnCancelled):
        workflow.generate_plan("T1", "1", 1)
    assert clicks == []
    meta = store.read_meta("T1", "1", 1)
    assert meta["generation"]["status"] == "cancelled"
    assert meta["generation"]["clicked"] is False
    assert meta["cancelled"]["before_click"] is True
    # A later turn under the old approval is refused, and the store fence agrees.
    token = progress.bind(progress.TurnControl("later", 60))
    try:
        refused = workflow.generate_plan("T1", "1", 1)
    finally:
        progress.unbind(token)
    assert refused["status"] == "cancelled" and refused["automatic_retry_allowed"] is False
    assert store.claim_generation("T1", "1", 1) is None
    assert clicks == []


def test_cancel_after_click_keeps_the_provider_result(store, bound, monkeypatch):
    prepare(store)
    clicks = []
    generation_stub(monkeypatch, clicks, after_click=lambda: bound.cancel("owner"))
    result = workflow.generate_plan("T1", "1", 1)
    assert result["status"] == "generated" and result["clicked"] is True
    assert clicks == ["IFD_T1_1_R1"]
    assert store.read_meta("T1", "1", 1)["generation"]["status"] == "generated"


def test_browser_queue_wait_honors_cancellation(bound):
    other = browser_budget.Lease()
    other.acquire()
    try:
        bound.cancel("owner")
        started = time.monotonic()
        with pytest.raises(progress.TurnCancelled):
            browser_budget.Lease().acquire()
        assert time.monotonic() - started < 2
        assert browser_budget.admission_status()["waiting"] == 0
    finally:
        other.finish(True)


def test_mark_cancelled_legs_keeps_completed_clicked_and_uncertain_work(store):
    for leg in "12345":
        prepare(store, leg=leg)
    store.save_meta("T1", "2", 1, {"briefing": "**SPAWN:**"})
    store.save_meta("T1", "3", 1, {"generation": {"status": "uncertain", "at": DEPARTURE}})
    store.save_meta("T1", "4", 1, {"generation": {"status": "generated", "at": DEPARTURE}})
    store.save_meta("T1", "5", 1, {"generation": {"status": "fill_mismatch", "retryable": True}})
    marked = progress.mark_cancelled_legs(["T1"], "thread-1", "owner")
    assert [m["leg"] for m in marked] == ["1", "5"]
    stages = {leg["leg"]: leg["stage"] for leg in progress.legs("T1")}
    assert stages == {
        "1": "cancelled",
        "2": "briefing_ready",
        "3": "generation_uncertain",
        "4": "generated_awaiting_finalize",
        "5": "cancelled",
    }
    assert progress.mark_cancelled_legs(["T1"], "thread-1", "owner") == []


def test_turn_record_persists_and_restart_is_reported_as_interrupted(monkeypatch):
    record = progress.start_turn("thread-r", "approve_dispatch")
    progress.set_status("thread-r", "running")
    assert progress.turn_view(progress.read("thread-r"), live=True)["status"] == "running"
    # A different server process (restart) cannot be running this turn.
    monkeypatch.setattr(progress, "BOOT_ID", "replacement-process")
    view = progress.turn_view(progress.read("thread-r"), live=False)
    assert view["status"] == "interrupted"
    assert view["interrupted_reason"] == "server_restarted"
    assert view["turn_id"] == record["turn_id"]
    monkeypatch.setattr(remote, "_turns", {})
    status = asyncio.run(remote.turn_status("thread-r"))
    assert status["status"] == "interrupted"
    assert "trip_progress" in status["next"]


class NoModel:
    """Checkpoint reader that fails the test if a turn would run the model."""

    def __init__(self, state):
        self.state = state

    def get_state(self, config):
        return self.state

    def invoke(self, *args, **kwargs):
        raise AssertionError("cancelled work must not invoke the model")


def empty_state():
    return SimpleNamespace(values={}, interrupts=())


def test_cancelled_queued_turn_starts_no_work(monkeypatch):
    monkeypatch.setattr(remote, "_get_agent", lambda: NoModel(empty_state()))
    progress.start_turn("thread-q", "plan_flight")
    control = progress.TurnControl("thread-q", 60)
    control.cancel("owner")
    result = remote._run({"messages": []}, "thread-q", control)
    assert result["status"] == "cancelled"
    assert progress.read("thread-q")["status"] == "cancelled"


def test_turn_deadline_is_recorded(monkeypatch):
    monkeypatch.setattr(remote, "_get_agent", lambda: NoModel(empty_state()))
    monkeypatch.setenv("IFD_TURN_DEADLINE_SECONDS", "0")
    record = progress.start_turn("thread-d", "plan_flight")
    assert record["deadline_seconds"] == 0
    result = remote._run({"messages": []}, "thread-d", progress.TurnControl("thread-d", 0))
    assert result["reason"] == "deadline_exceeded"
    assert progress.read("thread-d")["status"] == "deadline_exceeded"


def pending_state(store):
    interrupt = SimpleNamespace(
        id="interrupt-1",
        value={
            "action_requests": [
                {"name": "dispatch_flight", "args": {"trip": "T1", "leg": "2", "revision": 1}}
            ]
        },
    )
    message = SimpleNamespace(
        tool_calls=[{"name": "dispatch_flight", "args": {"trip": "T1", "leg": "1"}}]
    )
    return SimpleNamespace(values={"messages": [message]}, interrupts=(interrupt,))


def test_cancel_pending_approval_keeps_completed_legs_and_refuses_approval(store, monkeypatch):
    prepare(store, leg="1")
    store.save_meta("T1", "1", 1, {"briefing": "**SPAWN:** gate"})
    state = pending_state(store)
    monkeypatch.setattr(remote, "_get_agent", lambda: NoModel(state))
    monkeypatch.setattr(remote, "_turns", {})

    cancelled = asyncio.run(remote.cancel_trip("thread-a"))
    assert cancelled["status"] == "cancelled"
    assert cancelled["withdrawn_approval"]["inputs"]["leg"] == "2"
    assert cancelled["withdrawn_revisions"] == []
    assert cancelled["progress"]["completed_legs"] == [
        {"trip": "T1", "leg": "1", "revision": 1, "stage": "briefing_ready"}
    ]

    refused = asyncio.run(remote.approve_dispatch("thread-a", approve=True))
    assert refused["status"] == "cancelled"
    report = remote.trip_progress("thread-a")
    assert report["approval"]["pending"]["status"] == "cancelled"
    assert report["turn"]["status"] == "cancelled"
    assert remote.conversation_status("thread-a")["status"] == "approval_cancelled"
    assert store.read_meta("T1", "1", 1)["briefing"] == "**SPAWN:** gate"


def test_turn_status_reports_cancel_instead_of_stale_approval(store, monkeypatch):
    """Observed live on v0.5.0: turn_status kept returning the finished approval_required
    result after cancel_trip withdrew that approval."""
    from concurrent.futures import Future

    prepare(store, leg="1")
    state = pending_state(store)
    monkeypatch.setattr(remote, "_get_agent", lambda: NoModel(state))
    done = Future()
    done.set_result({"status": "approval_required", "thread_id": "thread-s"})
    monkeypatch.setattr(remote, "_turns", {"thread-s": done})

    assert asyncio.run(remote.turn_status("thread-s"))["status"] == "approval_required"
    assert asyncio.run(remote.cancel_trip("thread-s"))["status"] == "cancelled"
    status = asyncio.run(remote.turn_status("thread-s"))
    assert status["status"] == "cancelled"
    assert "cannot be approved" in status["next"]
    assert status["turn"]["status"] == "cancelled"


def test_trip_progress_not_found_and_records_approval_history(store, monkeypatch):
    monkeypatch.setattr(remote, "_get_agent", lambda: NoModel(empty_state()))
    assert remote.trip_progress("missing")["status"] == "not_found"
    state = pending_state(store)
    monkeypatch.setattr(remote, "_get_agent", lambda: NoModel(state))
    monkeypatch.setattr(remote, "_turns", {})

    async def answer():
        async def started(payload, thread_id, action):
            return {"status": "reply", "thread_id": thread_id}

        monkeypatch.setattr(remote, "_start", started)
        return await remote.approve_dispatch("thread-h", approve=False, note="no")

    assert asyncio.run(answer())["status"] == "reply"
    history = progress.read("thread-h")["approvals"]
    assert [(h["leg"], h["decision"]) for h in history] == [("2", "reject")]
    assert json.dumps(history)  # durable JSON record


def test_cancel_during_proposal_withdraws_the_new_approval_and_unclicked_dispatch(
    store, monkeypatch
):
    """Cancel lands while the model is proposing: no approval is offered, nothing generates."""
    state = pending_state(store)
    monkeypatch.setattr(remote, "_get_agent", lambda: NoModel(state))
    progress.start_turn("thread-p", "plan_flight")
    progress.update("thread-p", lambda r: r.update(cancel={"reason": "owner"}))
    control = progress.TurnControl("thread-p", 60)

    def invoke(payload, thread_id):
        prepare(store, leg="1")  # an approved dispatch saved just before the signal
        control.cancel("owner")
        return {"status": "approval_required", "thread_id": thread_id}

    monkeypatch.setattr(remote, "_invoke", invoke)
    result = remote._run({"messages": []}, "thread-p", control)
    assert result["status"] == "cancelled"
    record = progress.read("thread-p")
    assert record["status"] == "cancelled"
    assert record["cancel"]["outcome"] == "stopped"
    assert record["cancelled_interrupt"] == "interrupt-1"
    assert progress.pending_approval(state, record)["status"] == "cancelled"
    assert store.read_meta("T1", "1", 1)["cancelled"]["reason"] == "owner"
    assert store.claim_generation("T1", "1", 1) is None


def test_turn_that_finishes_before_seeing_cancel_is_confirmed_completed(monkeypatch):
    monkeypatch.setattr(remote, "_get_agent", lambda: NoModel(empty_state()))
    progress.start_turn("thread-c", "plan_flight")
    progress.update("thread-c", lambda r: r.update(cancel={"reason": "owner"}))
    control = progress.TurnControl("thread-c", 60)

    def invoke(payload, thread_id):
        control.cancel("owner")  # after the last boundary: the reply already exists
        return {"status": "reply", "thread_id": thread_id, "reply": "done"}

    monkeypatch.setattr(remote, "_invoke", invoke)
    assert remote._run({"messages": []}, "thread-c", control)["status"] == "reply"
    record = progress.read("thread-c")
    assert record["status"] == "reply" and record["cancel"]["outcome"] == "completed"


def test_stalled_call_is_stopped_at_the_next_boundary_by_the_deadline(monkeypatch):
    """Threads are not killed: a call stalled past the deadline stops at the next boundary."""
    monkeypatch.setattr(remote, "_get_agent", lambda: NoModel(empty_state()))
    progress.start_turn("thread-s", "plan_flight")
    middleware = progress.TurnControlMiddleware()
    after_stall = []

    def invoke(payload, thread_id):
        time.sleep(0.3)  # a model or provider call that outlives the turn deadline
        middleware.before_model({}, None)
        after_stall.append("next model call")
        return {"status": "reply", "thread_id": thread_id, "reply": "late"}

    monkeypatch.setattr(remote, "_invoke", invoke)
    result = remote._run({"messages": []}, "thread-s", progress.TurnControl("thread-s", 0.2))
    assert result["reason"] == "deadline_exceeded" and after_stall == []
    record = progress.read("thread-s")
    assert record["status"] == "deadline_exceeded"
    assert record["active_seconds"] >= 0.3


def test_active_time_counts_turns_only_not_the_approval_wait(monkeypatch):
    monkeypatch.setattr(remote, "_get_agent", lambda: NoModel(empty_state()))

    def invoke(payload, thread_id):
        time.sleep(0.1)
        return {"status": "reply", "thread_id": thread_id, "reply": "ok"}

    monkeypatch.setattr(remote, "_invoke", invoke)
    for _ in range(2):
        progress.start_turn("thread-t", "plan_flight")
        remote._run({"messages": []}, "thread-t", progress.TurnControl("thread-t", 60))
        time.sleep(0.4)  # the owner deciding between turns
    record = progress.read("thread-t")
    assert 0.2 <= record["active_seconds_total"] < 0.6
    view = progress.turn_view(record, live=False)
    assert view["finished_at"] and view["active_seconds"] >= 0.1
