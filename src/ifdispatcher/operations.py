"""Saved trip inspection, revisions and condition-specific N1 readings on the existing Store."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from ifdispatcher import planning, thrust
from ifdispatcher.core import open_store


def calibrated_estimate(store, data, engine, estimate, reading, simulator_version):
    if estimate["status"] != "estimated":
        return estimate, {"status": "unavailable"}
    scope = {
        "aircraft": data["aircraft"],
        "airframe_id": data.get("airframe_id"),
        "configuration": data.get("configuration"),
        "engine_override": engine,
        "conditions": (data.get("tlr") or {}).get("takeoff", {}).get("conditions"),
        "runway": data.get("selected_takeoff"),
        "simulator_version": simulator_version,
    }
    key = "n1_calibration:" + hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    record = None
    if reading is not None and simulator_version:
        record = {
            "scope": scope,
            "full_thrust_n1": reading,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        store.save_setting(key, json.dumps(record))
    elif reading is None and simulator_version:
        raw = store.read_setting(key)
        if raw:
            candidate = json.loads(raw)
            age = datetime.now(timezone.utc) - datetime.fromisoformat(candidate["observed_at"])
            if timedelta(0) <= age <= timedelta(days=7):
                record = candidate
                estimate = thrust.estimate_takeoff_n1(
                    data["aircraft"].get("icao_code"),
                    data["aircraft"].get("engines"),
                    scope["conditions"],
                    scope["runway"],
                    engine_override=engine,
                    full_thrust_n1=candidate["full_thrust_n1"],
                )
    return estimate, {
        "status": "saved"
        if reading is not None and record
        else "reused"
        if record
        else "supplied_for_this_plan"
        if reading is not None
        else "reading_needed",
        "observed_at": record["observed_at"] if record else None,
        "prompt": "To get an N1 percentage, give the full-throttle N1 shown in Infinite Flight on this runway at these weather and bleed/anti-ice settings. Include the simulator version to save it. Only supply an observed reading.",
        "scope": scope,
        "maximum_age_days": 7,
    }


def saved_trips(trip: str | None = None) -> dict:
    store = open_store()
    if trip is None:
        return {"status": "ok", "trips": store.trips()}
    legs = []
    for leg, request, meta in store.trip_legs(trip):
        try:
            snap = store.read(trip, leg, request["revision"])
        except ValueError:
            snap = None
        revisions = store.revisions(trip, leg)
        changes = {}
        if len(revisions) > 1:
            changes = {
                k: {"before": revisions[-2].get(k), "after": request.get(k)}
                for k in request
                if revisions[-2].get(k) != request.get(k)
            }
        legs.append(
            {
                "leg": leg,
                "request": request,
                "revision_changes": changes,
                "generation": {
                    k: (meta.get("generation") or {}).get(k)
                    for k in ("status", "clicked", "retryable")
                },
                "status": "briefing_ready"
                if meta.get("briefing")
                else "plan_retained"
                if snap
                else (meta.get("generation") or {}).get("status", "prepared"),
                "briefing_markdown": meta.get("briefing"),
                "task_outcome": meta.get("task_outcome"),
                "snapshot_sha256": snap["raw_sha256"] if snap else None,
            }
        )
    return {"status": "ok" if legs else "not_found", "trip": trip, "legs": legs}


EDITABLE = {
    "origin",
    "destination",
    "sim_aircraft",
    "departure_local_date",
    "departure_utc",
    "engine",
    "units",
    "passengers",
    "private_callsign",
    "fa_flight_id",
    "route",
    "runway",
    "airframe_id",
    "configuration",
    "simulator_capacity",
    "capacity_source",
    "arrival_target_utc",
}


def revision_inputs(trip: str, leg: str, changes: dict, base_revision: int) -> dict:
    from ifdispatcher import workflow

    unknown = set(changes) - EDITABLE
    if unknown:
        raise ValueError("unsupported_changes: " + ", ".join(sorted(unknown)))
    store = open_store()
    history = store.revisions(trip, leg)
    if not history:
        raise ValueError("missing_dispatch: no saved leg")
    request = history[-1]
    if request["revision"] != base_revision:
        raise ValueError(
            "revision_conflict: the leg changed since the approved base revision; inspect it and request new approval"
        )
    meta = store.read_meta(trip, leg, request["revision"])
    args = {k: v for k, v in request.items() if k in EDITABLE}
    args.update(
        sim_aircraft=request["aircraft"],
        departure_utc=request["departure"],
        departure_local_date=workflow.flights.local_time(request["departure"], request["origin"])[
            :10
        ],
        engine=meta.get("engine"),
        private_callsign=meta.get("private_callsign"),
        fa_flight_id=(meta.get("flight") or {}).get("fa_flight_id"),
    )
    args.update(changes)
    # A changed departure needs an explicit local date, rather than inheriting a wrong day.
    if (
        "departure_utc" in changes or "origin" in changes
    ) and "departure_local_date" not in changes:
        args["departure_local_date"] = workflow.flights.local_time(
            args["departure_utc"], args["origin"]
        )[:10]
    return dict(args, trip=trip, leg=leg, revision=request["revision"] + 1)


def revise(trip: str, leg: str, changes: dict, base_revision: int) -> dict:
    from ifdispatcher.workflow import dispatch_flight

    return dispatch_flight(**revision_inputs(trip, leg, changes, base_revision))


def refresh(trip: str, leg: str, revision: int = 1, simulator_version: str | None = None) -> dict:
    from ifdispatcher.workflow import finalize_dispatch

    old = open_store().read_meta(trip, leg, revision).get("briefing", "")
    result = finalize_dispatch(trip, leg, revision, simulator_version=simulator_version)
    new = result.get("briefing_markdown", "")
    result["changes"] = {
        "removed": [x for x in old.splitlines() if x and x not in new.splitlines()],
        "added": [x for x in new.splitlines() if x and x not in old.splitlines()],
    }
    result["refresh_scope"] = (
        "Saved immutable OFP and a fresh flight/gate observation; no SimBrief regeneration"
    )
    return result


def plan_arrival(
    origin: str, destination: str, arrival_local: str, block_time: str, duration_source: str
) -> dict:
    from ifdispatcher.flights import airport_timezone

    return planning.arrival_plan(
        arrival_local,
        airport_timezone(destination),
        block_time,
        duration_source,
        airport_timezone(origin),
    )
