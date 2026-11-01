"""The dispatcher Deep Agent: conversation and judgment, deterministic workflow tools.

Definition mirrors Managed Deep Agents fields (model, tools, interrupt_on; prompt from the
root instructions.md) so it can move to `define_deep_agent` later. Locally it runs with
GPT-6 Luna through Sign in with ChatGPT and a SQLite checkpointer for approvals.
"""

import argparse
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langchain.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from ifdispatcher import flights, thrust, workflow
from ifdispatcher.config import data_dir, export_tracing_settings, setting
from ifdispatcher.siwc import chatgpt_model

INSTRUCTIONS = (Path(__file__).resolve().parents[2] / "instructions.md").read_text()


def _safe(call, *args, **kwargs) -> dict[str, Any]:
    try:
        return call(*args, **kwargs)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}


@tool(parse_docstring=True)
def current_time() -> dict:
    """Current date and time in UTC and in Washington, D.C. (the user's home)."""
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("America/New_York"))
    return {
        "utc": now.isoformat(timespec="minutes"),
        "local": local.strftime("%A %Y-%m-%d %H:%M %Z"),
    }


@tool(parse_docstring=True)
def find_route_flights(
    origin: str, destination: str, local_date: str, airline: str | None = None
) -> dict:
    """Real nonstop airline flights between two airports on a local date (FlightAware).

    Args:
        origin: Departure airport ICAO code, e.g. KIAD.
        destination: Arrival airport ICAO code, e.g. KEWR.
        local_date: Departure date in the origin's local time, YYYY-MM-DD.
        airline: Optional 2-letter airline code to keep, e.g. UA (includes codeshares).
    """
    return _safe(flights.find_route_flights, origin, destination, local_date, airline)


@tool(parse_docstring=True)
def find_airport_departures(
    airport: str,
    local_date: str,
    start_local: str,
    end_local: str,
    airline: str | None = None,
    destination: str | None = None,
) -> dict:
    """Airline flights leaving an airport's gates within a local time window (max 3 hours).

    Args:
        airport: Airport ICAO code, e.g. KIAD.
        local_date: Local date, YYYY-MM-DD.
        start_local: Window start, local 24h HH:MM.
        end_local: Window end, local 24h HH:MM.
        airline: Optional airline code (2-letter IATA or 3-letter ICAO).
        destination: Optional destination ICAO code to keep.
    """
    return _safe(
        flights.find_airport_departures,
        airport,
        local_date,
        start_local,
        end_local,
        airline,
        destination,
    )


@tool(parse_docstring=True)
def get_flight_by_number(
    flight_number: str, local_date: str | None = None, origin: str | None = None
) -> dict:
    """Look up a flight number (IATA like UA495 or ICAO like UAL495) and its occurrences.

    Args:
        flight_number: The flight number.
        local_date: Optional date YYYY-MM-DD to narrow results.
        origin: Optional departure airport ICAO code to keep.
    """
    return _safe(flights.get_flight_by_number, flight_number, local_date, origin)


@tool(parse_docstring=True)
def recent_gates(flight_number: str, origin: str) -> dict:
    """Departure gates used by the most recent completed occurrences of a flight (past 10 days).
    Use when an upcoming flight has no gate yet; present it as historical, not an assignment.

    Args:
        flight_number: The flight number, e.g. UA495.
        origin: Departure airport ICAO code, e.g. KIAD.
    """
    return _safe(flights.recent_gates, flight_number, origin)


@tool(parse_docstring=True)
def thrust_support() -> dict:
    """Aircraft, engines and thrust modes the takeoff N1 estimator supports, and its inputs."""
    return thrust.supported_profiles()


@tool(parse_docstring=True)
def check_airports(codes: list[str]) -> dict:
    """FlightAware's name for each airport code, to confirm a code is the airport you mean.

    Args:
        codes: ICAO airport codes, e.g. ["KIAD", "CYQX"].
    """
    return {code.upper(): _safe(flights.airport_name, code) for code in codes}


@tool(parse_docstring=True)
def dispatch_flight(
    trip: str,
    leg: str,
    origin: str,
    destination: str,
    sim_aircraft: str,
    departure_local_date: str,
    revision: int = 1,
    fa_flight_id: str | None = None,
    departure_utc: str | None = None,
    engine: str | None = None,
    units: str = "KGS",
    passengers: int | None = None,
    private_callsign: str | None = None,
) -> dict:
    """Prepare one leg for SimBrief; the user's approval also authorizes generating it.

    Args:
        trip: Trip id shared by all legs, e.g. KIAD-KDEN-20261031.
        leg: Leg id in order: "1", "2", ...
        origin: Departure ICAO code.
        destination: Arrival ICAO code.
        sim_aircraft: SimBrief/Infinite Flight aircraft ICAO type, e.g. A21N.
        departure_local_date: Agreed departure date at the origin, local, YYYY-MM-DD.
        revision: 1 for a new leg; increase when material inputs change.
        fa_flight_id: FlightAware id of the verified airline flight (from a search result).
        departure_utc: ISO UTC departure; required for private flights.
        engine: Only if the user explicitly wants thrust for an engine other than the one SimBrief plans with.
        units: KGS or LBS, matching the user's SimBrief settings.
        passengers: Optional passenger count.
        private_callsign: Callsign for a private/GA flight (no airline flight number), 2-7 letters or digits such as the registration N172HD.
    """
    return _safe(
        workflow.dispatch_flight,
        trip,
        leg,
        origin,
        destination,
        sim_aircraft,
        departure_local_date,
        revision,
        fa_flight_id,
        departure_utc,
        engine,
        units,
        passengers,
        private_callsign,
    )


@tool(parse_docstring=True)
def generate_in_simbrief(trip: str, leg: str, revision: int = 1) -> dict:
    """Generate the approved leg in SimBrief: fill the dispatch form in the logged-in cloud
    browser, verify every value, and click Generate once. Call right after dispatch_flight
    succeeds (the user's dispatch approval covers it). Never call twice for one revision.

    Args:
        trip: Trip id used in dispatch_flight.
        leg: Leg id used in dispatch_flight.
        revision: Revision used in dispatch_flight.
    """
    return _safe(workflow.generate_plan, trip, leg, revision, True)


@tool(parse_docstring=True)
def finalize_dispatch(
    trip: str, leg: str, revision: int = 1, full_thrust_n1: float | None = None
) -> dict:
    """After generate_in_simbrief succeeds (or the user generated manually): fetch the plan once, verify, estimate thrust,
    refresh the gate, and return the final briefing.

    Args:
        trip: Trip id used in dispatch_flight.
        leg: Leg id used in dispatch_flight.
        revision: Revision used in dispatch_flight.
        full_thrust_n1: Optional N1 the user read in Infinite Flight at full throttle.
    """
    return _safe(workflow.finalize_dispatch, trip, leg, revision, full_thrust_n1)


@tool(parse_docstring=True)
def analyze_existing_plan(
    full_thrust_n1: float | None = None,
    engine: str | None = None,
    expected_origin: str | None = None,
    expected_destination: str | None = None,
    expected_flight_number: str | None = None,
) -> dict:
    """For a SimBrief plan the user ALREADY generated: fetch their latest plan once, estimate
    takeoff thrust, and look up the real flight's gate (or most recent gate). No dispatch needed.
    Pass what the user described; a different latest plan returns plan_mismatch.

    Args:
        full_thrust_n1: Optional N1 the user read in Infinite Flight at full throttle.
        engine: Only if the user explicitly wants thrust for a different engine than the plan's.
        expected_origin: Departure ICAO the user described, e.g. KIAD.
        expected_destination: Arrival ICAO the user described, e.g. KEWR.
        expected_flight_number: Flight number the user described, e.g. UA2408.
    """
    return _safe(
        workflow.analyze_existing_plan,
        full_thrust_n1,
        engine,
        expected_origin,
        expected_destination,
        expected_flight_number,
    )


TOOLS = [
    current_time,
    find_route_flights,
    find_airport_departures,
    get_flight_by_number,
    recent_gates,
    thrust_support,
    check_airports,
    dispatch_flight,
    generate_in_simbrief,
    finalize_dispatch,
    analyze_existing_plan,
]


def _airport_line(code: str | None) -> str:
    try:
        return f"{code}: {flights.airport_name(code or '')}"
    except ValueError as exc:
        return f"{code}: name unavailable ({exc})"


def approval_summary(tool_call, *_context) -> str:
    """What the user checks before approving a dispatch, built from the call, not the chat."""
    args = tool_call["args"]
    flight = args.get("fa_flight_id") or f"private, callsign {args.get('private_callsign')}"
    return "\n".join(
        [
            f"Leg {args.get('leg')} of {args.get('trip')}, {args.get('departure_local_date')}"
            f" ({flight})",
            f"From {_airport_line(args.get('origin'))}",
            f"To   {_airport_line(args.get('destination'))}",
            f"Simulator aircraft {args.get('sim_aircraft')}",
            f"Takeoff thrust: {thrust.support_note(args.get('sim_aircraft'))}",
        ]
    )


INTERRUPT_ON = {
    "dispatch_flight": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": approval_summary,
    }
}


class DispatchApproval(HumanInTheLoopMiddleware):
    """The dispatch approval gate, refusing several dispatches of one leg in one turn.

    Replaces Deep Agents' HumanInTheLoopMiddleware in place (same name). Two calls for the same
    trip, leg, and revision mean the model is offering alternatives; all dispatch calls in that
    turn are refused (never executed) so it chooses one or asks the user.
    """

    @property
    def name(self) -> str:
        return "HumanInTheLoopMiddleware"

    def _refuse_alternatives(self, state) -> dict | None:
        last = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
        calls = [c for c in (last.tool_calls if last else []) if c["name"] == "dispatch_flight"]
        legs = [
            (c["args"].get("trip"), c["args"].get("leg"), c["args"].get("revision", 1))
            for c in calls
        ]
        if len(set(legs)) == len(legs):
            return None
        reason = (
            "Several dispatch_flight calls for the same leg. Dispatch exactly one flight per leg: "
            "choose the best fit and say why in one line, or ask the user to choose."
        )
        content = json.dumps({"status": "refused", "reason": reason})
        return {
            "messages": [
                ToolMessage(content, tool_call_id=c["id"], name=c["name"], status="error")
                for c in calls
            ]
        }

    def after_model(self, state, runtime):
        return self._refuse_alternatives(state) or super().after_model(state, runtime)

    async def aafter_model(self, state, runtime):
        return self._refuse_alternatives(state) or await super().aafter_model(state, runtime)


# No `task` tool: Deep Agents' general-purpose subagent would get dispatch_flight without these
# instructions (observed in eval run 6, IFD-033). Profiles are per provider; the dispatcher's
# model is OpenAI (ChatGPT plan).
register_harness_profile(
    "openai",
    HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)),
)


def build_agent(model=None, checkpointer=None):
    return create_deep_agent(
        model=model or chatgpt_model("gpt-6-luna", "low"),
        tools=TOOLS,
        system_prompt=INSTRUCTIONS,
        interrupt_on=INTERRUPT_ON,
        middleware=[DispatchApproval(interrupt_on=INTERRUPT_ON)],
        checkpointer=checkpointer,
        name="infinite-flight-dispatcher",
    )


def checkpointer():
    """Postgres (Neon) when DATABASE_URL is set, else a local SQLite file.

    Neon closes idle connections, so the saver uses a pool that checks each connection
    before handing it out and reconnects instead of holding one connection forever.
    """
    dsn = setting("DATABASE_URL")
    if dsn:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            dsn,
            min_size=1,
            max_size=4,
            max_idle=60,
            kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
            check=ConnectionPool.check_connection,
            open=True,
        )
        saver = PostgresSaver(pool)
        saver.setup()
        return saver
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return SqliteSaver(sqlite3.connect(directory / "agent.sqlite", check_same_thread=False))


def _approval(interrupts) -> dict:
    decisions = []
    for request in interrupts[0].value["action_requests"]:
        print(f"\n[approval] {request['name']}:\n{request['description']}")
        print(json.dumps(request["args"], indent=2))
        answer = input("Approve? [y = approve / n = reject + reason]: ").strip()
        if answer.lower().startswith("y"):
            decisions.append({"type": "approve"})
        else:
            decisions.append({"type": "reject", "message": answer or "rejected by user"})
    return {"decisions": decisions}


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the Infinite Flight Dispatcher")
    parser.add_argument("--thread", default=None, help="resume a saved conversation thread")
    args = parser.parse_args()
    export_tracing_settings()
    thread = args.thread or f"chat-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread}}
    agent = build_agent(checkpointer=checkpointer())
    print(f"Thread {thread}. Ctrl-D to exit.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except EOFError:
            break
        if not text:
            continue
        payload: Any = {"messages": [{"role": "user", "content": text}]}
        while True:
            result = agent.invoke(payload, config=config, version="v2")
            if result.interrupts:
                payload = Command(resume=_approval(result.interrupts))
                continue
            print("\ndispatcher>", result.value["messages"][-1].text)
            break
