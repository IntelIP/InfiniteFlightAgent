"""Recovery at approval and pre-click readback boundaries; all providers controlled."""

import json

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ifdispatcher import agent, workflow
from ifdispatcher.core import open_store
from test_agent_workflow import ScriptedModel


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("IFD_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(agent.flights, "airport_name", lambda code: "Controlled airport")
    monkeypatch.setattr(agent.flights, "airport_elevation", lambda code: 300)
    monkeypatch.setattr(agent.flights, "local_time", lambda value, code: value)
    monkeypatch.setattr(workflow.artifacts, "upload", lambda *a: [])
    return open_store()


def dispatch(leg="1", trip="T"):
    return {
        "trip": trip,
        "leg": leg,
        "origin": "KIAD",
        "destination": "KEWR",
        "sim_aircraft": "A20N",
        "departure_local_date": "2026-11-08",
        "departure_utc": "2026-11-08T12:00:00Z" if leg == "1" else "2026-11-08T18:00:00Z",
        "private_callsign": "N320HD",
        "passengers": 4,
    }


@pytest.mark.parametrize("second_trip", ["T", "OTHER"])
@pytest.mark.parametrize("approve", [False, True])
def test_batched_dispatch_recovers_to_one_exact_approval(isolated, second_trip, approve):
    one, two = dispatch(), dispatch("2", second_trip)
    calls = [
        {"name": "dispatch_flight", "id": "batch-one", "args": one},
        {"name": "dispatch_flight", "id": "batch-two", "args": two},
    ]
    graph = agent.build_agent(
        model=ScriptedModel(
            [
                AIMessage("", tool_calls=calls),
                AIMessage(
                    "", tool_calls=[{"name": "dispatch_flight", "id": "single", "args": one}]
                ),
                AIMessage("First leg decision received."),
            ]
        ),
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "batch-recovery"}}
    first = graph.invoke(
        {"messages": [{"role": "user", "content": "Prepare the settled itinerary."}]},
        config,
        version="v2",
    )
    actions = first.interrupts[0].value["action_requests"]
    assert len(actions) == 1 and actions[0]["args"] == one
    refused = [m for m in first.value["messages"] if m.type == "tool"]
    assert [m.tool_call_id for m in refused] == ["batch-one", "batch-two"]
    assert all(json.loads(m.content)["status"] == "refused" for m in refused)
    assert all("one leg at a time" in json.loads(m.content)["reason"] for m in refused)
    assert isolated.trips() == []
    done = graph.invoke(
        Command(resume={"decisions": [{"type": "approve" if approve else "reject"}]}),
        config,
        version="v2",
    )
    assert not done.interrupts
    assert bool(isolated.trips()) is approve
    if approve:
        assert [leg for leg, _, _ in isolated.trip_legs("T")] == ["1"]


def mismatch():
    return {"status": "fill_mismatch", "mismatched": {"pax": {"want": "4", "got": "0"}}}


def prepare():
    return workflow.dispatch_flight(**dispatch())


def test_prepared_dispatch_tells_agent_to_continue_after_existing_approval(isolated):
    result = prepare()
    assert "already approved" in result["next_step"]
    assert "generate_in_simbrief" in result["next_step"]


def test_first_safe_readback_mismatch_can_refill_once_without_new_consent(isolated, monkeypatch):
    prepare()
    original = isolated.read_request("T", "1", 1)
    calls, clicks = [], []

    def generate(fields, click, _shots, before_click):
        calls.append(fields.copy())
        if len(calls) == 1:
            return mismatch()
        before_click()
        clicks.append(True)
        return {"status": "generated"}

    monkeypatch.setattr(workflow.simbrief_browser, "generate", generate)
    first = workflow.generate_plan("T", "1")
    assert first["automatic_retry_allowed"] is True
    assert first["clicked"] is False and first["retryable"] is True
    assert "once" in first["next"] and "generate_in_simbrief" in first["next"]
    assert isolated.read_request("T", "1", 1) == original
    assert isolated.read_meta("T", "1", 1)["generation"]["fill_mismatch_count"] == 1
    second = workflow.generate_plan("T", "1")
    assert second["status"] == "generated"
    assert calls[0] == calls[1] and len(clicks) == 1
    assert workflow.generate_plan("T", "1")["status"] == "already_attempted"
    assert len(calls) == 2


def test_repeated_readback_mismatch_fences_further_provider_attempts(isolated, monkeypatch):
    prepare()
    calls = []

    def generate(*args, **kwargs):
        calls.append(True)
        return mismatch()

    monkeypatch.setattr(workflow.simbrief_browser, "generate", generate)
    assert workflow.generate_plan("T", "1")["automatic_retry_allowed"] is True
    second = workflow.generate_plan("T", "1")
    assert second["automatic_retry_allowed"] is False
    assert second["retryable"] is False and second["clicked"] is False
    assert "new approved revision" in second["next"]
    stopped = workflow.generate_plan("T", "1")
    assert stopped["status"] == "already_attempted"
    assert stopped["automatic_retry_allowed"] is False
    assert len(calls) == 2


@pytest.mark.parametrize(
    "status,click",
    [
        ("uncertain", True),
        ("needs_review", True),
        ("not_logged_in", True),
        ("fill_mismatch", False),
    ],
)
def test_other_outcomes_and_dry_runs_do_not_gain_automatic_retry(
    isolated, monkeypatch, status, click
):
    prepare()
    monkeypatch.setattr(workflow.simbrief_browser, "generate", lambda *a, **k: {"status": status})
    result = workflow.generate_plan("T", "1", click=click)
    assert result["automatic_retry_allowed"] is False


def test_post_click_mismatch_does_not_gain_automatic_retry(isolated, monkeypatch):
    prepare()

    def generate(fields, click, _shots, before_click):
        before_click()
        return mismatch()

    monkeypatch.setattr(workflow.simbrief_browser, "generate", generate)
    result = workflow.generate_plan("T", "1")
    assert result["clicked"] is True and result["retryable"] is False
    assert result["automatic_retry_allowed"] is False
