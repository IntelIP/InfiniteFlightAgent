"""Local stdio tools. No generation endpoint is claimed or invoked."""

import logging
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ifdispatcher import thrust
from ifdispatcher.config import setting
from ifdispatcher.core import Dispatch, Identifier, fetch, open_store

mcp = FastMCP("InfiniteFlightDispatcher")


def store():
    return open_store()


@mcp.tool()
def simbrief_capabilities() -> dict[str, Any]:
    """Check implemented operations and blockers before planning a dispatch workflow."""
    return {
        "preparation": True,
        "retrieval": True,
        "saved_snapshots": True,
        "generation": False,
        "generation_blocker": "Authorized developer contract/access missing",
        "thrust_calculation": "simulation_grade_estimate (A20N/A21N TOGA/FLEX; B38M TO/TO-1/TO-2, D-)",
    }


@mcp.tool()
def prepare_simbrief_dispatch(request: Dispatch) -> dict[str, Any]:
    """Prepare a leg; return missing inputs. Saves complete inputs locally, never submits.

    Pass UTC-aware departure, explicit KGS/LBS units, and aircraft/custom profile identity.
    Change revision when any agreed input changes. Unspecified options use provider defaults.
    """
    return store().prepare(request)


@mcp.tool()
async def retrieve_simbrief_plan(
    trip: Identifier,
    leg: Identifier,
    revision: int,
    user_requested: bool,
    static_id: str | None = None,
) -> dict[str, Any]:
    """Fetch once on explicit user request, then save against a prepared leg revision.

    Never poll for generation. Requires SIMBRIEF_ALIAS or SIMBRIEF_USERID. A matching route
    does not prove generation succeeded; this tool imports an existing OFP only.
    """
    if not user_requested:
        raise ValueError("user_action_required: no automatic latest-plan polling")
    raw = await fetch(setting("SIMBRIEF_ALIAS"), static_id, userid=setting("SIMBRIEF_USERID"))
    return store().save(trip, leg, revision, raw, static_id)


@mcp.tool()
def read_simbrief_snapshot(trip: Identifier, leg: Identifier, revision: int) -> dict[str, Any]:
    """Read a saved leg revision locally without fetching or changing the latest plan."""
    return store().read(trip, leg, revision)


@mcp.tool()
def estimate_takeoff_n1(
    trip: Identifier,
    leg: Identifier,
    revision: int,
    engine_override: str | None = None,
    full_thrust_n1: Annotated[float, Field(gt=40, le=120)] | None = None,
) -> dict[str, Any]:
    """Estimate takeoff N1 (labeled simulation-grade) from a saved A20N/A21N/B38M snapshot.

    Uses the snapshot's selected takeoff runway: thrust mode/derate, FLEX or assumed temp, OAT, altimeter,
    elevation, bleeds. Pass engine_override when the Infinite Flight livery's engine differs
    from SimBrief's (e.g. PW1133G-JM). Pass full_thrust_n1, the N1 read in Infinite Flight at
    full throttle on the runway, to get an absolute target. Never present the result as a
    manufacturer value; keep its label, range, and assumptions in the briefing.
    """
    data = store().read(trip, leg, revision)["data"]
    tlr = data.get("tlr") or {}
    return thrust.estimate_takeoff_n1(
        aircraft_icao=data["aircraft"].get("icao_code"),
        engines=data["aircraft"].get("engines"),
        conditions=(tlr.get("takeoff") or {}).get("conditions"),
        runway=data.get("selected_takeoff"),
        engine_override=engine_override,
        full_thrust_n1=full_thrust_n1,
    )


def main():
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
