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
