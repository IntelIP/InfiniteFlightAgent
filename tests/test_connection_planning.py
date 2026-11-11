"""Controlled connection planning and actual approval-graph scenarios; no providers."""

import json

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ifdispatcher import agent, workflow
from ifdispatcher.core import Dispatch, Store
from test_agent_workflow import ScriptedModel


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("IFD_DATA_DIR", str(tmp_path))
    store = Store(tmp_path)
    monkeypatch.setattr(workflow, "_store", lambda: store)
    monkeypatch.setattr(agent.flights, "airport_name", lambda code: "Controlled airport")
    monkeypatch.setattr(agent.flights, "airport_elevation", lambda code: 300)
    monkeypatch.setattr(agent.flights, "local_time", lambda value, code: value)
    return store


def proposed(**changes):
    return {
        "trip": "planned-trip",
        "leg": "2",
        "departure_utc": "2026-11-08T17:00:00Z",
        "previous_leg": "1",
        "previous_arrival_utc": "2026-11-08T16:00:00Z",
        "arrival_source": "FlightAware controlled occurrence UA100 scheduled_in",
        **changes,
    }


def save_previous(store, arrival=None):
    store.prepare(
        Dispatch(
            trip="planned-trip",
            leg="1",
            revision=1,
            origin="KIAD",
            destination="KEWR",
            aircraft="A20N",
            departure="2026-11-08T14:00:00Z",
            units="KGS",
        )
    )
    if arrival:
        store.save_meta("planned-trip", "1", 1, {"planned_arrival": arrival})


def test_proposed_search_connection_is_computed_without_saving_or_confirming(isolated):
    result = agent.check_connection.invoke(proposed())
    assert result["status"] == "proposed"
    assert result["follows"] == {
        "leg": "1",
        "arrival_utc": "2026-11-08T16:00:00Z",
        "connection": "1 h 00 min",
    }
    assert result["arrival_source"] == proposed()["arrival_source"]
    assert "recheck" in result["next"].lower()
    assert isolated.trips() == []


@pytest.mark.parametrize("missing", ["previous_leg", "previous_arrival_utc", "arrival_source"])
def test_proposed_connection_requires_complete_evidence(isolated, missing):
    args = proposed()
    args.pop(missing)
    result = agent.check_connection.invoke(args)
    assert result["status"] == "error"
    assert "connection_evidence_required" in result["error"]
    assert isolated.trips() == []


def test_private_unknown_arrival_returns_actionable_unavailable(isolated):
    save_previous(isolated)
    result = agent.check_connection.invoke(
        {"trip": "planned-trip", "leg": "2", "departure_utc": "2026-11-08T17:00:00Z"}
    )
    assert result["status"] == "arrival_unavailable"
    assert "follows" not in result
    assert "finalize" in result["next"].lower()
    assert "confirm" not in result["next"].lower()


def test_no_saved_previous_leg_does_not_request_confirmation(isolated):
    result = agent.check_connection.invoke(
        {"trip": "planned-trip", "leg": "1", "departure_utc": "2026-11-08T14:00:00Z"}
    )
    assert result["status"] == "no_previous_leg"
    assert "confirm" not in result["next"].lower()


def test_retained_arrival_overrides_older_candidate_evidence(isolated):
    save_previous(isolated, "2026-11-08T16:30:00Z")
    result = agent.check_connection.invoke(proposed())
    assert result["status"] == "conflict"
    assert result["follows"]["connection"] == "0 h 30 min"
    assert result["follows"]["arrival_utc"] == "2026-11-08T16:30:00Z"
    assert result["arrival_source"] == "retained leg 1"


@pytest.mark.parametrize(
    "arrival,departure,gap,conflict",
    [
        ("2026-11-01T01:30:00-04:00", "2026-11-01T01:30:00-05:00", "1 h 00 min", False),
        ("2026-11-12T09:00:00+13:00", "2026-11-11T14:00:00-08:00", "2 h 00 min", False),
        ("2026-11-08T16:00:00Z", "2026-11-08T16:20:00Z", "0 h 20 min", True),
    ],
)
def test_connection_uses_absolute_time_and_changed_departure(
    isolated, arrival, departure, gap, conflict
):
    result = agent.check_connection.invoke(
        proposed(previous_arrival_utc=arrival, departure_utc=departure)
    )
    assert result["follows"]["connection"] == gap
    assert ("conflict" in result) is conflict
    assert result["status"] == ("conflict" if conflict else "proposed")


@pytest.mark.parametrize("arrival", ["2026-11-08T16:00:00", "not-a-date"])
def test_proposed_arrival_needs_a_real_timezone_aware_value(isolated, arrival):
    result = agent.check_connection.invoke(proposed(previous_arrival_utc=arrival))
    assert result["status"] == "error"
    assert isolated.trips() == []


@pytest.mark.parametrize("approve", [False, True])
def test_planning_before_dispatch_keeps_exact_approval_and_rejection(isolated, approve):
    dispatch = {
        "trip": "planned-trip",
        "leg": "1",
        "origin": "KIAD",
        "destination": "KEWR",
        "sim_aircraft": "A20N",
        "departure_local_date": "2026-11-08",
        "departure_utc": "2026-11-08T14:00:00Z",
        "private_callsign": "N320HD",
    }
    graph = agent.build_agent(
        model=ScriptedModel(
            [
                AIMessage(
                    "", tool_calls=[{"name": "check_connection", "args": proposed(), "id": "c"}]
                ),
                AIMessage(
                    "", tool_calls=[{"name": "dispatch_flight", "args": dispatch, "id": "d"}]
                ),
                AIMessage("Prepared." if approve else "Declined."),
            ]
        ),
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "connection-approval"}}
    first = graph.invoke(
        {"messages": [{"role": "user", "content": "Use these settled private flight inputs."}]},
        config,
    )
    action = first["__interrupt__"][0].value["action_requests"][0]
    assert action["name"] == "dispatch_flight" and action["args"] == dispatch
    assert isolated.trips() == []
    result = graph.invoke(
        Command(resume={"decisions": [{"type": "approve" if approve else "reject"}]}), config
    )
    outputs = [
        json.loads(m.content)
        for m in result["messages"]
        if m.type == "tool" and m.name == "check_connection"
    ]
    assert outputs[0]["status"] == "proposed"
    assert bool(isolated.trips()) is approve


def test_changed_departure_before_previous_leg_is_a_conflict(isolated):
    save_previous(isolated, "2026-11-08T16:00:00Z")
    result = agent.check_connection.invoke(
        {"trip": "planned-trip", "leg": "2", "departure_utc": "2026-11-08T13:00:00Z"}
    )
    assert result["status"] == "conflict"
    assert result["follows"]["leg"] == "1"
    assert "before" in result["conflict"]


def test_early_later_leg_dispatch_does_not_write_a_leg(isolated):
    save_previous(isolated, "2026-11-08T16:00:00Z")
    result = workflow.dispatch_flight(
        "planned-trip",
        "2",
        "KEWR",
        "KIAD",
        "A20N",
        "2026-11-08",
        private_callsign="N320HD",
        departure_utc="2026-11-08T13:00:00Z",
    )
    assert result["status"] == "connection_conflict"
    assert [leg for leg, _, _ in isolated.trip_legs("planned-trip")] == ["1"]


def test_changed_first_leg_cannot_depart_after_following_leg(isolated):
    isolated.prepare(
        Dispatch(
            trip="planned-trip",
            leg="2",
            revision=1,
            origin="KEWR",
            destination="KIAD",
            aircraft="A20N",
            departure="2026-11-08T17:00:00Z",
            units="KGS",
        )
    )
    result = agent.check_connection.invoke(
        {"trip": "planned-trip", "leg": "1", "departure_utc": "2026-11-08T18:00:00Z"}
    )
    assert result["status"] == "conflict"
    assert "following leg 2" in result["conflict"]
