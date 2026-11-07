"""Trace-derived regression journeys: real tool graph/storage, controlled providers, no paid calls."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ifdispatcher import agent, operations, planning, remote, thrust, workflow
from ifdispatcher.core import Dispatch, open_store
from test_agent_workflow import ScriptedModel, neo_plan


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("IFD_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(workflow.flights, "airport_name", lambda code: "Test airport")
    monkeypatch.setattr(workflow.flights, "airport_elevation", lambda code: 312)
    monkeypatch.setattr(workflow.flights, "local_time", lambda value, code: value)
    monkeypatch.setattr(workflow.flights, "airport_timezone", lambda code: "UTC")
    return open_store()


def prepare(**extra):
    return workflow.dispatch_flight(
        "T",
        "1",
        "KIAD",
        "KEWR",
        "A21N",
        "2026-11-08",
        departure_utc="2026-11-08T12:00:00Z",
        private_callsign="N320HD",
        **extra,
    )


def fuel_plan():
    raw = json.loads(neo_plan(datetime.now(timezone.utc).isoformat(), "2026-11-08T12:00:00Z"))
    raw["fuel"] = dict(
        plan_ramp="10000",
        plan_takeoff="9700",
        min_takeoff="9000",
        plan_landing="2000",
        max_tanks="20000",
        reserve="800",
        alternate_burn="1000",
    )
    return raw


def test_auckland_plan_is_not_presented_as_flyable(local_store, monkeypatch):
    prepare()
    raw = fuel_plan()
    # Values observed in the retained KLAX-NZAA plan on 2026-11-07; this is an excerpt-based
    # regression, not a fresh provider response or a simulator test.
    raw["fuel"].update(
        plan_ramp="20503",
        max_tanks="19117",
        min_takeoff="31642",
        plan_takeoff="20273",
        plan_landing="-7101",
        reserve="785",
        alternate_burn="2114",
    )
    raw["general"] = {"sys_rmk": ["WARNING: FLIGHT EXCEEDS AIRCRAFT RANGE"]}
    monkeypatch.setattr(workflow, "fetch_sync", lambda *a, **k: json.dumps(raw).encode())
    result = workflow.finalize_dispatch("T", "1")
    assert result["feasibility"]["status"] == "infeasible"
    assert result["task_outcome"] == "infeasible"
    assert "withheld" in result["briefing_markdown"]
    assert "FLIGHT EXCEEDS AIRCRAFT RANGE" in result["briefing_markdown"]
    assert "negative" in result["briefing_markdown"]
    assert operations.saved_trips("T")["legs"][0]["task_outcome"] == "infeasible"


def test_capacity_requires_source_and_units_stay_explicit(local_store):
    assert prepare(simulator_capacity=15000)["status"] == "missing_input"
    raw = fuel_plan()
    result = planning.assess(
        raw, {"simulator_capacity": 9000, "capacity_source": "IF 26.3 fuel screen"}
    )
    assert result["status"] == "infeasible" and result["simulator_status"] == "capacity_exceeded"
    assert planning.assess(raw)["simulator_status"] == "unknown"
    assert planning.assess({})["status"] == "unknown"


def test_arrival_planner_crosses_date_line_and_refuses_dst_ambiguity():
    result = planning.arrival_plan(
        "2026-11-08T07:00",
        "Pacific/Auckland",
        "13:19:38",
        "retained SimBrief est_block",
        "America/Los_Angeles",
    )
    assert result["departure_utc"].startswith("2026-11-07T04:40:22")
    assert result["departure_local"].startswith("2026-11-06T20:40:22-08:00")
    for local in ("2026-11-01T01:30", "2026-03-08T02:30"):
        with pytest.raises(ValueError, match="ambiguous_arrival"):
            planning.arrival_plan(local, "America/New_York", "02:00", "estimate")


def test_calibration_reused_only_for_matching_conditions_version_and_age(local_store, monkeypatch):
    prepare()
    raw = fuel_plan()
    monkeypatch.setattr(workflow, "fetch_sync", lambda *a, **k: json.dumps(raw).encode())
    first = workflow.finalize_dispatch("T", "1", full_thrust_n1=92, simulator_version="26.3")
    assert first["calibration"]["status"] == "saved"
    assert "set N1" in first["briefing_markdown"] and "% (range" in first["briefing_markdown"]
    reused = workflow.finalize_dispatch("T", "1", simulator_version="26.3")
    assert reused["calibration"]["status"] == "reused"
    assert (
        workflow.finalize_dispatch("T", "1", simulator_version="26.4")["calibration"]["status"]
        == "reading_needed"
    )
    assert workflow.finalize_dispatch("T", "1")["calibration"]["status"] == "reading_needed"
    data = local_store.read("T", "1", 1)["data"]
    data["tlr"]["takeoff"]["conditions"]["temperature"] = "39"
    estimate = thrust.estimate_takeoff_n1(
        data["aircraft"]["icao_code"],
        data["aircraft"]["engines"],
        data["tlr"]["takeoff"]["conditions"],
        data["selected_takeoff"],
    )
    assert (
        operations.calibrated_estimate(local_store, data, None, estimate, None, "26.3")[1]["status"]
        == "reading_needed"
    )
    with local_store.connect() as db:
        rows = db.execute("SELECT name, value FROM settings").fetchall()
    for key, value in rows:
        record = json.loads(value)
        record["observed_at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        local_store.save_setting(key, json.dumps(record))
    assert (
        workflow.finalize_dispatch("T", "1", simulator_version="26.3")["calibration"]["status"]
        == "reading_needed"
    )


def test_revision_requires_graph_approval_and_preserves_old_plan(local_store, monkeypatch):
    prepare(route="DCT", passengers=15)
    old = fuel_plan()
    local_store.save("T", "1", 1, json.dumps(old).encode(), None)
    call = {
        "name": "revise_dispatch",
        "id": "r1",
        "args": {
            "trip": "T",
            "leg": "1",
            "base_revision": 1,
            "changes": {"passengers": 12, "route": "DCT NEW"},
        },
    }
    graph = agent.build_agent(
        model=ScriptedModel([AIMessage("", tool_calls=[call]), AIMessage("Revision prepared.")]),
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "revision"}}
    result = graph.invoke(
        {"messages": [{"role": "user", "content": "Change load and route"}]}, config, version="v2"
    )
    assert result.interrupts
    assert local_store.read_request("T", "1", 2) is None
    graph.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config, version="v2")
    assert local_store.read_request("T", "1", 2)["passengers"] == 12
    assert local_store.read("T", "1", 1)["data"]["aircraft"]["icao_code"] == "A21N"
    state = operations.saved_trips("T")["legs"][0]
    assert state["snapshot_sha256"] is None
    assert state["revision_changes"]["route"] == {"before": "DCT", "after": "DCT NEW"}


def test_custom_profile_must_match_retained_airframe(local_store):
    request = Dispatch(
        trip="P",
        leg="1",
        revision=1,
        origin="KIAD",
        destination="KEWR",
        aircraft="A21N",
        departure=datetime.now(timezone.utc),
        units="KGS",
        airframe_id="123_456",
    )
    local_store.prepare(request)
    raw = fuel_plan()
    raw["aircraft"]["internal_id"] = "A21N"
    with pytest.raises(ValueError, match="selected SimBrief airframe differs"):
        local_store.save("P", "1", 1, json.dumps(raw).encode(), None)
    raw["aircraft"]["internal_id"] = "123_456"
    assert local_store.save("P", "1", 1, json.dumps(raw).encode(), None)["status"] == "saved"


def test_restart_can_read_persisted_conversation_without_model(monkeypatch):
    state = SimpleNamespace(values={"messages": [AIMessage("Saved reply")]}, interrupts=[])
    monkeypatch.setattr(remote, "_get_agent", lambda: SimpleNamespace(get_state=lambda _: state))
    assert remote.conversation_status("old-thread")["reply"] == "Saved reply"


def test_workflow_feedback_does_not_equate_generation_with_completion():
    from ifdispatcher.observability import summarize

    msg = ToolMessage(
        json.dumps({"status": "generated"}), name="generate_in_simbrief", tool_call_id="x"
    )
    result = summarize([msg], set())
    assert result["outcome"] == "conversation" and result["user_task_completed"] is None


@pytest.mark.parametrize("reading", [float("nan"), float("inf"), 0, 140, True])
def test_invalid_calibration_never_becomes_target(reading):
    assert (
        thrust.estimate_takeoff_n1("A20N", None, None, None, full_thrust_n1=reading)["status"]
        == "invalid_input"
    )


def test_computed_connection_is_in_route_search_before_dispatch(local_store, monkeypatch):
    prepare()
    meta = local_store.read_meta("T", "1", 1)
    meta["flight"] = {"times": {"scheduled_in": {"utc": "2026-11-08T15:00:00Z"}}}
    local_store.save_meta("T", "1", 1, meta)
    candidate = {"times": {"scheduled_out": {"utc": "2026-11-08T16:16:00Z"}}}
    monkeypatch.setattr(
        agent.flights,
        "find_route_flights",
        lambda *a: {"status": "ok", "data": [candidate]},
    )
    result = agent.find_route_flights.invoke(
        {
            "origin": "KEWR",
            "destination": "KIAD",
            "local_date": "2026-11-08",
            "trip": "T",
            "leg": "2",
        }
    )
    assert result["data"][0]["connection_check"]["follows"]["connection"] == "1 h 16 min"


def test_refresh_changes_gate_without_generating_or_replacing_plan(local_store, monkeypatch):
    prepare()
    raw = fuel_plan()
    monkeypatch.setattr(workflow, "fetch_sync", lambda *a, **k: json.dumps(raw).encode())
    first = workflow.finalize_dispatch("T", "1")
    meta = local_store.read_meta("T", "1", 1)
    from test_agent_workflow import flight

    meta["flight"] = flight()
    local_store.save_meta("T", "1", 1, meta)
    new = flight()
    new["departure_gate"] = "D17"
    monkeypatch.setattr(workflow.flights, "refresh_flight", lambda *a: {"data": new})
    monkeypatch.setattr(
        workflow.simbrief_browser, "generate", lambda *a, **k: pytest.fail("no regeneration")
    )
    refreshed = operations.refresh("T", "1")
    assert "Gate D17" in refreshed["briefing_markdown"]
    assert any("Gate D17" in line for line in refreshed["changes"]["added"])
    assert first["snapshot"]["sha256"] == refreshed["snapshot"]["sha256"]


def test_persisted_approval_survives_agent_reconstruction(local_store, monkeypatch, tmp_path):
    from langgraph.checkpoint.sqlite import SqliteSaver

    call = {
        "name": "dispatch_flight",
        "id": "approval",
        "args": {
            "trip": "T",
            "leg": "1",
            "origin": "KIAD",
            "destination": "KEWR",
            "sim_aircraft": "A20N",
            "departure_local_date": "2026-11-08",
            "departure_utc": "2026-11-08T12:00:00Z",
            "private_callsign": "N320HD",
        },
    }
    config = {"configurable": {"thread_id": "persisted-approval"}}
    path = str(tmp_path / "checkpoint.sqlite")
    with SqliteSaver.from_conn_string(path) as saver:
        graph = agent.build_agent(
            model=ScriptedModel([AIMessage("", tool_calls=[call])]), checkpointer=saver
        )
        assert graph.invoke(
            {"messages": [{"role": "user", "content": "prepare"}]}, config, version="v2"
        ).interrupts
    with SqliteSaver.from_conn_string(path) as saver:
        restarted = agent.build_agent(model=ScriptedModel([]), checkpointer=saver)
        monkeypatch.setattr(remote, "_get_agent", lambda: restarted)
        assert remote.conversation_status("persisted-approval")["status"] == "approval_required"


def test_replay_blocks_new_browser_tool_and_isolates_new_storage(local_store):
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path("evals").resolve()))
    import run_eval
    from unittest.mock import patch

    case = {
        "id": "isolation",
        "prompt": "test isolation",
        "category": "edge_cases",
        "fixture": "evals/fixtures/synthetic/SYNTH-001.json",
    }

    def exercise(*a):
        with pytest.raises(ValueError, match="eval_scope"):
            workflow.simbrief_browser.airframes("A20N")
        assert operations.open_store().trips() == []
        return {"id": "isolation", "error": None}

    prepare()
    with patch.object(run_eval, "_run_case", exercise):
        result = run_eval.run_case(case, None, 1, "test")
    assert not result["invalid"] and local_store.trips() == ["T"]


def test_generation_claim_is_shared_across_reopened_store(local_store):
    prepare()
    first = local_store.claim_generation("T", "1", 1)
    assert first["generation"]["status"] == "clicking"
    assert open_store().claim_generation("T", "1", 1) is None
    assert open_store().read_meta("T", "1", 1)["generation"]["at"] == first["generation"]["at"]


def test_existing_revision_from_before_extension_still_prepares(local_store):
    prepare()
    with local_store.connect() as db:
        row = db.execute("SELECT payload FROM requests WHERE trip='T'").fetchone()
        payload = json.loads(row[0])
        for key in (
            "airframe_id",
            "configuration",
            "simulator_capacity",
            "capacity_source",
            "arrival_target_utc",
        ):
            payload.pop(key)
        db.execute("UPDATE requests SET payload=? WHERE trip='T'", (json.dumps(payload),))
    assert prepare()["status"] == "awaiting_simbrief_generation"


def test_autopopulated_route_is_default_but_explicit_route_is_checked():
    from ifdispatcher.simbrief_browser import form_mismatches

    want = {"route": "", "date": "09 Nov 2026 - 05:00", "pax": "15"}
    got = {**want, "route": "SUMMR2 FICKY TONYS B200 AKLOM EXOP8D"}
    assert form_mismatches({"route": None}, want, got) == {}
    assert "route" in form_mismatches({"route": "DCT"}, dict(want, route="DCT"), got)
    assert "pax" in form_mismatches({"route": None}, want, dict(got, pax="0"))


def test_frontmost_unknown_dialog_is_never_clicked_through():
    from ifdispatcher.simbrief_browser import _answer_known_prompts

    class Dialog:
        def __init__(self, text):
            self.text = text

        def evaluate(self, script):
            return 100

        def inner_text(self):
            return self.text

        def get_by_role(self, *a, **k):
            pytest.fail("must not click behind unknown front dialog")

    dialogs = [Dialog("departure time has changed"), Dialog("No Alternates Found")]
    locator = SimpleNamespace(filter=lambda **k: SimpleNamespace(all=lambda: dialogs))
    page = SimpleNamespace(wait_for_timeout=lambda _: None, get_by_role=lambda _: locator)
    assert _answer_known_prompts(page) == []


def test_revision_cannot_rebase_itself_after_approval(local_store):
    prepare()
    operations.revise("T", "1", {"passengers": 4}, 1)
    with pytest.raises(ValueError, match="approved base revision"):
        operations.revise("T", "1", {"passengers": 8}, 1)
    assert local_store.read_request("T", "1", 3) is None


def test_private_connection_uses_the_retained_plans_arrival(local_store, monkeypatch):
    prepare()
    raw = fuel_plan()
    raw["times"]["est_in"] = "2026-11-08T14:00:00Z"
    monkeypatch.setattr(workflow, "fetch_sync", lambda *a, **k: json.dumps(raw).encode())
    workflow.finalize_dispatch("T", "1")
    fit = workflow.connection("T", "2", "2026-11-08T14:10:00Z")
    assert "conflict" in fit and "0 h 10 min" in fit["conflict"]
