"""Workflow spine tests. FlightAware and SimBrief are MOCKED here (guards, not live behavior)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ifdispatcher import workflow

FIXTURE = Path("docs/research/evidence/simbrief-b38m-parser-fixture.json")
OUT_UTC = "2026-10-31T21:37:00Z"


def flight(local="2026-10-31 17:37 EDT"):
    return {
        "flight_number": "UA1831",
        "codeshares": ["ET1386"],
        "fa_flight_id": "UAL1831-test",
        "origin": {"icao": "KIAD", "iata": "IAD"},
        "destination": {"icao": "KEWR", "iata": "EWR"},
        "times": {
            "scheduled_out": {"utc": OUT_UTC, "local": local},
            "estimated_out": {"utc": OUT_UTC, "local": local},
        },
        "departure_gate": "C23",
        "aircraft_type": "A319",
        "registration": "N843UA",
        "observed_at": "2026-10-30T23:00:00Z",
    }


def neo_plan(generated: str, sched_out: str = OUT_UTC) -> bytes:
    raw = json.loads(FIXTURE.read_text())
    raw["aircraft"].update(icao_code="A21N", icaocode="A21N", engines="LEAP-1A33")
    raw["params"]["time_generated"] = generated
    raw["times"] = {"sched_out": sched_out, "est_time_enroute": "00:46:20"}
    runway = next(r for r in raw["tlr"]["takeoff"]["runway"] if r["identifier"] == "30")
    runway.update(thrust_setting="FLEX", flex_temperature="50")
    return json.dumps(raw).encode()


@pytest.fixture
def mocked(tmp_path, monkeypatch):
    monkeypatch.setenv("IFD_DATA_DIR", str(tmp_path))
    state = {"flight": flight(), "plan": None}
    monkeypatch.setattr(
        workflow.flights, "refresh_flight", lambda _id: {"status": "ok", "data": state["flight"]}
    )
    monkeypatch.setattr(workflow, "fetch_sync", lambda *a, **k: state["plan"])
    return state


def dispatch(date="2026-10-31", **extra):
    return workflow.dispatch_flight(
        "KIAD-KEWR-20261031",
        "1",
        "KIAD",
        "KEWR",
        "A21N",
        date,
        fa_flight_id="UAL1831-test",
        engine="PW1133G-JM",
        **extra,
    )


def test_wrong_occurrence_date_is_refused(mocked):
    result = dispatch(date="2026-11-01")
    assert result["status"] == "flight_mismatch"
    assert "2026-10-31" in result["reason"]


def test_dispatch_returns_simbrief_inputs(mocked):
    result = dispatch()
    assert result["status"] == "awaiting_simbrief_generation"
    inputs = result["simbrief_inputs"]
    assert (inputs["airline"], inputs["flight_number"], inputs["date"]) == ("UA", "1831", "31OCT26")
    assert inputs["departure_time_utc"] == "21:37"


def test_private_flight_needs_callsign_or_flight(mocked):
    result = workflow.dispatch_flight("T", "1", "KIAD", "KTEB", "A20N", "2026-10-31")
    assert result["status"] == "missing_input"


def test_finalize_refuses_plan_generated_before_dispatch(mocked):
    dispatch()
    mocked["plan"] = neo_plan("2026-10-29T00:15:52Z")
    result = workflow.finalize_dispatch("KIAD-KEWR-20261031", "1")
    assert result["status"] == "stale_plan"


def test_finalize_refuses_wrong_departure_time(mocked):
    dispatch()
    now = datetime.now(timezone.utc)
    mocked["plan"] = neo_plan(now.isoformat(), (now + timedelta(days=3)).isoformat())
    assert workflow.finalize_dispatch("KIAD-KEWR-20261031", "1")["status"] == "plan_mismatch"


def test_finalize_composes_briefing(mocked):
    dispatch()
    mocked["plan"] = neo_plan(datetime.now(timezone.utc).isoformat())
    result = workflow.finalize_dispatch("KIAD-KEWR-20261031", "1", full_thrust_n1=90.0)
    assert result["status"] == "complete"
    brief = result["briefing_markdown"]
    assert brief.startswith("**SPAWN:** Gate C23")
    assert "TAKEOFF THRUST (simulation-grade estimate):** FLEX" in brief
    assert "PW1133G-JM" in brief  # livery engine override, not SimBrief's LEAP
    assert result["thrust"]["data"]["calibration_full_thrust_n1"] == 90.0
    assert "UA1831 (ET1386)" in brief and "real aircraft A319" in brief


def test_generation_clicks_at_most_once_per_revision(mocked, monkeypatch):
    dispatch()
    calls = []

    def fake_generate(fields, click, shots_dir):
        calls.append((fields["origin"], fields["destination"], fields["airline"], click))
        return {"status": "generated", "session": "https://www.browserbase.com/sessions/x"}

    monkeypatch.setattr(workflow.simbrief_browser, "generate", fake_generate)
    first = workflow.generate_plan("KIAD-KEWR-20261031", "1", 1)
    second = workflow.generate_plan("KIAD-KEWR-20261031", "1", 1)
    assert first["status"] == "generated"
    assert second["status"] == "already_attempted"
    assert calls == [("KIAD", "KEWR", None, True)]  # mocked flight has no ICAO ident


def test_finalize_refuses_plan_older_than_the_generate_click(mocked, monkeypatch):
    dispatch()
    monkeypatch.setattr(
        workflow.simbrief_browser, "generate", lambda *a: {"status": "generated", "session": "s"}
    )
    workflow.generate_plan("KIAD-KEWR-20261031", "1", 1)
    mocked["plan"] = neo_plan((datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat())
    assert workflow.finalize_dispatch("KIAD-KEWR-20261031", "1")["status"] == "stale_plan"


def test_briefing_falls_back_to_most_recent_completed_gate(mocked, monkeypatch):
    mocked["flight"]["departure_gate"] = "unavailable"
    dispatch()
    monkeypatch.setattr(
        workflow.flights,
        "recent_gates",
        lambda number, origin: {
            "data": {"most_recent": {"gate": "C27", "date_local": "2026-10-30"}}
        },
    )
    mocked["plan"] = neo_plan(datetime.now(timezone.utc).isoformat())
    brief = workflow.finalize_dispatch("KIAD-KEWR-20261031", "1")["briefing_markdown"]
    assert brief.startswith("**SPAWN:** Gate C27 — used by the most recent completed UA1831")
    assert "today's gate is not assigned yet" in brief


def test_private_callsign_must_fit_icao_limit(mocked):
    result = workflow.dispatch_flight(
        "T",
        "1",
        "KJYO",
        "KFDK",
        "C172",
        "2026-10-31",
        departure_utc="2026-10-31T16:00:00Z",
        private_callsign="N172HUDSON",
    )
    assert result["status"] == "invalid_input"


def test_dispatch_reports_thrust_support(mocked):
    assert dispatch()["thrust_estimate"].startswith("supported")
    private = workflow.dispatch_flight(
        "T",
        "1",
        "KJYO",
        "KFDK",
        "C172",
        "2026-10-31",
        departure_utc="2026-10-31T16:00:00Z",
        private_callsign="N172HD",
    )
    assert private["thrust_estimate"].startswith("unavailable: C172")


def test_existing_plan_mismatch_is_reported_not_briefed(mocked):
    mocked["plan"] = neo_plan(datetime.now(timezone.utc).isoformat())  # KIAD -> KEWR
    result = workflow.analyze_existing_plan(expected_origin="KIAD", expected_destination="KDEN")
    assert result["status"] == "plan_mismatch"
    assert result["differences"]["destination"] == {"described": "KDEN", "latest_plan": "KEWR"}
    assert "briefing_markdown" not in result


def test_approval_summary_names_airports_and_thrust(monkeypatch):
    from ifdispatcher import agent, flights

    names = {
        "/airports/KIAD": {"name": "Dulles Int'l", "city": "Washington", "country_code": "US"},
        "/airports/CYYT": {"name": "St. John's Int'l", "city": "St. John's", "country_code": "CA"},
    }
    monkeypatch.setattr(flights, "_get", lambda path, params=None: names[path])
    call = {
        "args": {
            "trip": "T",
            "leg": "1",
            "origin": "KIAD",
            "destination": "CYYT",
            "sim_aircraft": "TBM9",
            "departure_local_date": "2026-11-01",
            "private_callsign": "N930HD",
        }
    }
    summary = agent.approval_summary(call)
    assert "CYYT: St. John's Int'l (St. John's, CA)" in summary  # a wrong code is visible
    assert "takeoff N1 estimate unavailable" in summary
    assert "private, callsign N930HD" in summary


def test_approval_summary_survives_lookup_failure(monkeypatch):
    from ifdispatcher import agent, flights

    def down(path, params=None):
        raise ValueError("paid_operations_disabled")

    monkeypatch.setattr(flights, "_get", down)
    summary = agent.approval_summary(
        {"args": {"origin": "KIAD", "destination": "KEWR", "sim_aircraft": "A20N"}}
    )
    assert "KIAD: name unavailable (paid_operations_disabled)" in summary
    assert "A20N: simulation-grade takeoff N1 estimate available" in summary


def ScriptedModel(messages):
    """Plays fixed AI messages through the real agent graph (no model calls)."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class Model(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    return Model(messages=iter(messages))


def test_two_dispatches_of_one_leg_are_refused_before_approval(monkeypatch):
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from ifdispatcher import agent

    monkeypatch.setattr(agent.flights, "airport_name", lambda code: "Test airport")  # no AeroAPI
    leg = {
        "trip": "T",
        "leg": "1",
        "origin": "KIAD",
        "destination": "KSFO",
        "sim_aircraft": "A21N",
        "departure_local_date": "2026-10-31",
    }
    calls = [
        {"name": "dispatch_flight", "args": {**leg, "fa_flight_id": fid}, "id": f"c{i}"}
        for i, fid in enumerate(["UAL2862-x", "UAL796-x"])
    ]
    model = ScriptedModel([AIMessage("", tool_calls=calls), AIMessage("Which flight?")])
    graph = agent.build_agent(model=model, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t"}}
    result = graph.invoke({"messages": [{"role": "user", "content": "go"}]}, config, version="v2")

    assert not result.interrupts  # never reached the approval gate
    refused = [m for m in result.value["messages"] if m.type == "tool"]
    assert [m.tool_call_id for m in refused] == ["c0", "c1"]
    assert all('"refused"' in m.content for m in refused)
    assert result.value["messages"][-1].text == "Which flight?"


def test_one_dispatch_per_leg_still_needs_approval(monkeypatch):
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from ifdispatcher import agent

    monkeypatch.setattr(agent.flights, "airport_name", lambda code: "Test airport")  # no AeroAPI
    call = {
        "name": "dispatch_flight",
        "id": "c0",
        "args": {
            "trip": "T",
            "leg": "1",
            "origin": "KIAD",
            "destination": "KSFO",
            "sim_aircraft": "A21N",
            "departure_local_date": "2026-10-31",
            "fa_flight_id": "UAL796-x",
        },
    }
    graph = agent.build_agent(
        model=ScriptedModel([AIMessage("", tool_calls=[call])]), checkpointer=InMemorySaver()
    )
    config = {"configurable": {"thread_id": "t"}}
    result = graph.invoke({"messages": [{"role": "user", "content": "go"}]}, config, version="v2")
    assert result.interrupts
    assert result.interrupts[0].value["action_requests"][0]["name"] == "dispatch_flight"


def test_agent_has_no_task_subagent():
    # A general-purpose subagent would reach dispatch_flight without the dispatcher's
    # instructions. Building the agent makes no model or network call.
    from ifdispatcher import agent
    from ifdispatcher.siwc import chatgpt_model

    graph = agent.build_agent(model=chatgpt_model("gpt-6-luna", "low"))
    tools = graph.get_graph().nodes["tools"].data.tools_by_name
    assert "task" not in tools and "dispatch_flight" in tools
