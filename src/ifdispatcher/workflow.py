"""Deterministic dispatch spine called by the agent: prepare a leg, then finalize it.

dispatch_flight runs only after the user approves the exact inputs (agent interrupt_on).
finalize_dispatch fetches the latest SimBrief plan once, refuses stale or mismatched plans,
resolves thrust, refreshes the gate, and composes the briefing from data, not model text.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ifdispatcher import artifacts, flights, planning, progress, simbrief_browser, thrust
from ifdispatcher.config import data_dir, setting
from ifdispatcher.core import Dispatch, Store, fetch_sync, normalize, open_store

MAX_DEPARTURE_DRIFT = timedelta(hours=3)
MIN_CONNECTION = timedelta(minutes=45)


def _store() -> Store:
    return open_store()


def _arrival(meta: dict) -> datetime | None:
    """A live flight's expected arrival, or the retained plan's arrival for private legs."""
    times = (meta.get("flight") or {}).get("times") or {}
    value = (times.get("estimated_in") or {}).get("utc") or (times.get("scheduled_in") or {}).get(
        "utc"
    )
    value = value or meta.get("planned_arrival")
    return _utc(value) if value else None


def _duration(gap: timedelta) -> str:
    minutes = int(abs(gap.total_seconds()) // 60)
    return f"{minutes // 60} h {minutes % 60:02d} min"


def _relative(gap: timedelta) -> str:
    return f"{_duration(gap)} {'after' if gap >= timedelta(0) else 'before'}"


def connection(
    trip: str,
    leg: str,
    departure: datetime | str,
    arrival: datetime | None = None,
    *,
    previous_leg: str | None = None,
    previous_arrival_utc: str | None = None,
    arrival_source: str | None = None,
) -> dict[str, Any]:
    """Check retained arrivals, or a labeled proposed connection from supplied evidence.

    Proposed evidence never writes a leg or replaces a known retained arrival. The actual
    dispatch still checks its saved neighbours after exact-input approval.
    """
    departure = _utc(departure) if isinstance(departure, str) else departure
    supplied = any(v is not None for v in (previous_leg, previous_arrival_utc, arrival_source))
    if supplied and not all(
        isinstance(v, str) and v.strip()
        for v in (previous_leg, previous_arrival_utc, arrival_source)
    ):
        raise ValueError(
            "connection_evidence_required: provide previous_leg, previous_arrival_utc "
            "with timezone, and arrival_source together"
        )
    proposed_arrival = _utc(previous_arrival_utc) if supplied else None
    if supplied and previous_leg == leg:
        raise ValueError("invalid_previous_leg: a leg cannot connect to itself")
    others = [
        (other, _utc(request["departure"]), _arrival(meta))
        for other, request, meta in _store().trip_legs(trip)
        if other != leg and request.get("departure")
    ]
    # Numbered legs represent itinerary order even when a changed departure crosses
    # another leg's departure. Legacy named-leg trips retain their time-based ordering.
    numbered = str(leg).isdecimal() and all(str(o[0]).isdecimal() for o in others)
    earlier = [o for o in others if (int(o[0]) < int(leg) if numbered else o[1] < departure)]
    prior = max(earlier, key=lambda o: int(o[0]) if numbered else o[1]) if earlier else None
    if prior and supplied and previous_leg != prior[0]:
        raise ValueError(
            "previous_leg_mismatch: supplied evidence is not for the preceding saved leg"
        )
    if prior and proposed_arrival and proposed_arrival <= prior[1]:
        raise ValueError("invalid_previous_arrival: arrival must follow that leg's departure")

    fit: dict[str, Any] = {}
    landed = prior[2] if prior else None
    if landed:
        previous = prior[0]
        fit.update(status="checked", arrival_source=f"retained leg {previous}")
    elif proposed_arrival:
        previous, landed = previous_leg, proposed_arrival
        fit.update(
            status="proposed",
            arrival_source=arrival_source,
            next="Proposed timing only; keep estimates labeled and recheck against the retained "
            "prior leg before dispatching this leg. Do not ask to reconfirm settled choices.",
        )
    elif prior:
        fit.update(
            status="arrival_unavailable",
            previous_leg=prior[0],
            next="Finalize the prior leg to obtain its planned arrival, then recheck. "
            "The connection remains unknown until that arrival is available.",
        )
    else:
        fit.update(
            status="no_previous_leg",
            next="Prepare the first agreed leg. For a proposed later connection, supply the "
            "previous leg's sourced arrival or finalize that leg first.",
        )
    if landed:
        gap = departure - landed
        fit["follows"] = {
            "leg": previous,
            "arrival_utc": landed.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "connection": _duration(gap),
        }
        if gap < MIN_CONNECTION:
            fit["status"] = "conflict"
            fit["conflict"] = (
                f"Leg {leg} departs {_relative(gap)} leg {previous} arrives "
                f"({landed:%Y-%m-%d %H:%MZ}); a connection needs at least "
                f"{_duration(MIN_CONNECTION)}. Choose a later flight for leg {leg}."
            )
            fit["next"] = "Choose a later departure and recompute; do not dispatch this connection."
    later = [o for o in others if (int(o[0]) > int(leg) if numbered else o[1] >= departure)]
    if later and "conflict" not in fit:
        following, leaves, _ = min(later, key=lambda o: int(o[0]) if numbered else o[1])
        if departure >= leaves:
            fit["status"] = "conflict"
            fit["conflict"] = (
                f"Leg {leg} departs at or after following leg {following}; choose an earlier "
                "departure or revise the following leg."
            )
        elif arrival and leaves - arrival < MIN_CONNECTION:
            fit["status"] = "conflict"
            fit["conflict"] = (
                f"Leg {leg} arrives {arrival:%Y-%m-%d %H:%MZ}, {_relative(arrival - leaves)} "
                f"leg {following} departs; a connection needs at least "
                f"{_duration(MIN_CONNECTION)}."
            )
        if "conflict" in fit:
            fit["next"] = "Revise the conflicting departure and recompute before dispatching."
    return fit


def _utc(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("invalid_departure: include a timezone (e.g. 2026-10-31T02:10:00Z)")
    return moment.astimezone(timezone.utc)


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
    route: str | None = None,
    runway: str | None = None,
    airframe_id: str | None = None,
    configuration: str | None = None,
    simulator_capacity: float | None = None,
    capacity_source: str | None = None,
    arrival_target_utc: str | None = None,
) -> dict[str, Any]:
    origin, destination, sim_aircraft = origin.upper(), destination.upper(), sim_aircraft.upper()
    flight = None
    if fa_flight_id:
        checked = flights.refresh_flight(fa_flight_id)
        flight = checked.get("data")
        if not flight:
            return {"status": "flight_not_found", "reason": f"no AeroAPI flight {fa_flight_id}"}
        if (flight["origin"]["icao"], flight["destination"]["icao"]) != (origin, destination):
            return {
                "status": "flight_mismatch",
                "reason": "verified flight route differs from the requested leg",
                "flight": flight,
            }
        flight_date = (flight["times"]["scheduled_out"]["local"] or "")[:10]
        if flight_date != departure_local_date:
            return {
                "status": "flight_mismatch",
                "reason": f"this flight departs on {flight_date} local, not "
                f"{departure_local_date}; pick the occurrence for the agreed date",
                "flight": flight,
            }
        departure_utc = departure_utc or flight["times"]["scheduled_out"]["utc"]
    elif not private_callsign:
        return {
            "status": "missing_input",
            "missing_inputs": ["fa_flight_id from a flight search, or private_callsign"],
        }
    if private_callsign and not re.fullmatch(r"[A-Z0-9]{2,7}", private_callsign.upper()):
        return {
            "status": "invalid_input",
            "reason": "private_callsign must be 2-7 letters or digits (ICAO limit), e.g. N172HD",
        }
    if not departure_utc:
        return {"status": "missing_input", "missing_inputs": ["departure_utc"]}
    if simulator_capacity is not None and not capacity_source:
        return {
            "status": "missing_input",
            "missing_inputs": ["capacity_source (where simulator fuel capacity was observed)"],
        }
    departure = _utc(departure_utc)
    if flight:
        scheduled = _utc(flight["times"]["scheduled_out"]["utc"])
        if abs(scheduled - departure) > MAX_DEPARTURE_DRIFT:
            return {"status": "flight_mismatch", "reason": "departure differs from the schedule"}
    fit = connection(trip, leg, departure, _arrival({"flight": flight}) if flight else None)
    if "conflict" in fit:
        return {"status": "connection_conflict", "reason": fit["conflict"]}

    request = Dispatch(
        trip=trip,
        leg=leg,
        revision=revision,
        origin=origin,
        destination=destination,
        aircraft=sim_aircraft,
        departure=departure,
        units=units.upper(),
        passengers=passengers,
        route=route,
        runway=runway,
        airframe_id=airframe_id,
        configuration=configuration,
        simulator_capacity=simulator_capacity,
        capacity_source=capacity_source,
        arrival_target_utc=arrival_target_utc,
    )
    store = _store()
    prepared = store.prepare(request)
    if prepared["status"] != "prepared":
        return prepared
    old_meta = store.read_meta(trip, leg, revision)
    if old_meta and (
        old_meta.get("engine"),
        old_meta.get("private_callsign"),
        (old_meta.get("flight") or {}).get("fa_flight_id"),
    ) != (engine, private_callsign, fa_flight_id):
        return {
            "status": "revision_conflict",
            "reason": "Flight, engine or callsign changed; use a new revision",
        }
    store.save_meta(
        trip,
        leg,
        revision,
        {
            **old_meta,
            "flight": flight,
            "engine": engine,
            "private_callsign": private_callsign,
            "prepared_at": old_meta.get("prepared_at") or datetime.now(timezone.utc).isoformat(),
        },
    )
    number = flight["flight_number"] if flight else private_callsign
    airline, digits = (number[:2], number[2:]) if flight and number else (None, None)
    return {
        "status": "awaiting_simbrief_generation",
        "connection": fit.get("follows"),
        "trip": trip,
        "leg": leg,
        "revision": revision,
        "simbrief_inputs": {
            "airline": airline,
            "flight_number": digits,
            "callsign": private_callsign.upper() if private_callsign else None,
            "departure": origin,
            "arrival": destination,
            "date": departure.strftime("%d%b%y").upper(),
            "departure_time_utc": departure.strftime("%H:%M"),
            "aircraft_type": sim_aircraft,
            "units": units.upper(),
            "passengers": passengers,
            "takeoff_performance": "enable runway analysis (TLR)",
            "route": route if route is not None else "SimBrief default",
            "runway": runway,
            "airframe_id": airframe_id,
            "configuration": configuration,
        },
        "thrust_estimate": "supported (labeled simulation-grade estimate)"
        if sim_aircraft in thrust.AIRCRAFT
        else f"unavailable: {sim_aircraft} is not modeled; tell the user before generating",
        "next_step": (
            "The exact dispatch inputs are already approved. Call generate_in_simbrief now "
            "without asking for another go-ahead, then finalize_dispatch on generated. "
            "If generation fails, follow its retry/recovery guidance."
        ),
        "flight": flight,
        "warnings": [
            "Custom/ACJ configuration and simulator capacity are not verified by the aircraft name alone"
        ]
        if configuration
        else [],
    }


def _tag(trip: str, leg: str, revision: int) -> str:
    return f"IFD_{re.sub(r'[^A-Za-z0-9]', '', trip)[:24]}_{leg}_R{revision}"


class GenerationClaimed(ValueError):
    """Another execution already owns this leg revision's Generate click."""


def _cancelled_result(meta: dict) -> dict[str, Any]:
    return {
        "status": "cancelled",
        "reason": "This approved revision was cancelled before its Generate click; its approval "
        "no longer authorizes generation.",
        "next": "Ask the user, then request a new approved revision with revise_dispatch to continue.",
        "cancelled": meta.get("cancelled"),
        "clicked": False,
        "retryable": False,
        "automatic_retry_allowed": False,
    }


def generate_plan(trip: str, leg: str, revision: int = 1, click: bool = True) -> dict[str, Any]:
    """Fill SimBrief's dispatch form in the logged-in cloud browser and (if click) Generate once."""
    store = _store()
    request = store.read_request(trip, leg, revision)
    if not request:
        return {"status": "missing_dispatch", "reason": "call dispatch_flight for this leg first"}
    meta = store.read_meta(trip, leg, revision)
    previous = (meta.get("generation") or {}).get("status")
    if click and meta.get("cancelled"):
        return _cancelled_result(meta)
    if (
        click
        and previous in ("clicking", "generated", "uncertain", "error", "fill_mismatch")
        and not (meta.get("generation") or {}).get("retryable")
    ):
        return {
            "status": "already_attempted",
            "reason": (
                "Safe refill retry exhausted before Generate; review the mismatch. "
                "Further generation requires a new approved revision; do not finalize."
                if previous == "fill_mismatch"
                else f"generation already {previous} for this leg revision; finalize it, or "
                "dispatch a new revision if the user wants to regenerate"
            ),
            "generation": meta.get("generation"),
            "retryable": False,
            "automatic_retry_allowed": False,
        }
    flight = meta.get("flight") or {}
    ident = re.fullmatch(r"([A-Z]{3})(\d+[A-Z]?)", flight.get("ident_icao") or "")
    fields = {
        "airline": ident.group(1) if ident else None,
        "flight_number": ident.group(2) if ident else None,
        "callsign": meta.get("private_callsign"),
        "origin": request["origin"],
        "destination": request["destination"],
        "aircraft": request["aircraft"],
        "units": request["units"],
        "passengers": request.get("passengers"),
        "departure_utc": request["departure"],
        "tag": _tag(trip, leg, revision),
    }

    def mark_clicking() -> None:  # just before the click: earlier failures leave the leg retryable
        nonlocal meta
        progress.check()  # the last safe point to honor cancellation or the turn deadline
        claimed = store.claim_generation(trip, leg, revision)
        if claimed is None:
            if store.read_meta(trip, leg, revision).get("cancelled"):
                raise progress.TurnCancelled("cancelled")
            raise GenerationClaimed("Generation already claimed for this revision")
        meta = claimed

    fields.update({k: request.get(k) for k in ("route", "runway", "airframe_id")})
    try:
        result = simbrief_browser.generate(
            fields, click, data_dir() / "screens", before_click=mark_clicking if click else None
        )
    except GenerationClaimed:
        return {
            "status": "already_attempted",
            "retryable": False,
            "reason": "Another execution already claimed Generate for this revision",
        }
    except progress.TurnCancelled as exc:
        # Raised only before the click (browser admission or the pre-click check).
        meta = store.read_meta(trip, leg, revision)
        meta["generation"] = {
            **meta.get("generation", {}),
            "status": "cancelled",
            "clicked": False,
            "retryable": False,
            "automatic_retry_allowed": False,
            "reason_code": exc.reason,
        }
        meta.setdefault(
            "cancelled",
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "reason": exc.reason,
                "before_click": True,
            },
        )
        store.save_meta(trip, leg, revision, meta)
        raise
    except Exception as exc:
        clicked = (meta.get("generation") or {}).get("status") == "clicking"
        result = {
            "status": "uncertain" if clicked else "error",
            "error": type(exc).__name__,
            "session": getattr(exc, "simbrief_session", None),
            "clicked": clicked,
            "retryable": not clicked,
            **simbrief_browser.generation_failure(exc, clicked),
        }
        meta["generation"] = {**meta.get("generation", {}), **result}
        store.save_meta(trip, leg, revision, meta)
        return result
    clicked = (meta.get("generation") or {}).get("status") == "clicking"
    result.update(
        clicked=clicked,
        retryable=not clicked and result["status"] not in ("generated", "uncertain"),
        automatic_retry_allowed=False,
    )
    if click and result["status"] == "fill_mismatch" and not clicked:
        mismatches = (meta.get("generation") or {}).get("fill_mismatch_count", 0) + 1
        retry = mismatches == 1
        result.update(
            fill_mismatch_count=mismatches,
            retryable=retry,
            automatic_retry_allowed=retry,
            next=(
                "Refill the same approved inputs and call generate_in_simbrief once more in "
                "the current browser workflow. Existing dispatch approval covers this "
                "correction; do not ask for another go-ahead or open a replacement browser."
                if retry
                else "Form readback mismatched again before Generate. Stop and review the "
                "mismatch; further generation requires a new approved revision. Do not finalize."
            ),
        )
    if result["status"] == "uncertain":
        result.update(
            reason_code="generation_outcome_unknown",
            reason="Generate was clicked, but completion was not observed.",
            next=simbrief_browser.UNCERTAIN_GENERATION_NEXT,
            automatic_retry_allowed=False,
        )
    try:
        result["r2_keys"] = artifacts.upload(
            result.get("screenshots") or [], f"screens/{fields['tag']}"
        )
    except Exception as exc:  # screenshots are evidence, not required for the dispatch
        result["r2_error"] = type(exc).__name__
    if click:
        meta["generation"] = {**meta.get("generation", {}), **result, "status": result["status"]}
        store.save_meta(trip, leg, revision, meta)
    return result


def _synopsis(raw: dict) -> dict[str, Any]:
    general, times, fuel = raw.get("general", {}), raw.get("times", {}), raw.get("fuel", {})
    weights, units = raw.get("weights", {}), raw.get("params", {}).get("units")
    altitude = general.get("initial_altitude")
    navlog = raw.get("navlog")
    fixes = navlog.get("fix") if isinstance(navlog, dict) else None
    if isinstance(fixes, dict):
        fixes = [fixes]
    if not isinstance(fixes, list) or not all(isinstance(fix, dict) for fix in fixes):
        fixes = None
    return {
        "generated_at": raw.get("params", {}).get("time_generated"),
        "flight": f"{general.get('icao_airline') or ''}{general.get('flight_number') or ''}",
        "route": f"{raw['origin'].get('icao_code')} {raw['origin'].get('plan_rwy')} -> "
        f"{raw['destination'].get('icao_code')} {raw['destination'].get('plan_rwy')}",
        "aircraft": f"{raw['aircraft'].get('icao_code')} {raw['aircraft'].get('engines')}",
        "cruise": f"FL{int(altitude) // 100}" if altitude and altitude.isdigit() else altitude,
        "distance_nm": general.get("route_distance"),
        "ete": times.get("est_time_enroute"),
        "block_fuel": f"{fuel.get('plan_ramp')} {units}",
        "takeoff_weight": f"{weights.get('est_tow')} {units}",
        "passengers": weights.get("pax_count"),
        "sched_out": times.get("sched_out"),
        "arrival": times.get("est_in"),
        "block_time": times.get("est_block"),
        "flight_route": general.get("route"),
        "navlog_fix_count": len(fixes) if fixes is not None else None,
        "navlog_idents": [fix.get("ident") for fix in fixes] if fixes is not None else None,
    }


def _briefing(syn: dict, flight: dict | None, est: dict, takeoff: dict | None, meta: dict) -> str:
    if flight:
        gate = flight["departure_gate"]
        last = (meta.get("recent_gates") or {}).get("most_recent")
        if gate != "unavailable":
            spawn = (
                f"Gate {gate} (reported by FlightAware at {flight['observed_at']}; "
                "simulator stand not verified)"
            )
        elif last:
            spawn = (
                f"Gate {last['gate']} — used by the most recent completed {flight['flight_number']} "
                f"({last['date_local']}, FlightAware); today's gate is not assigned yet"
            )
        else:
            spawn = "Gate not assigned yet and no recent gate found; choose a suitable stand"
    else:
        spawn = (
            "No real flight matched: choose a stand or FBO/GA ramp that fits your aircraft "
            "(not verified)"
            if meta.get("private_callsign") is None
            else "Private flight: no assigned gate; choose an FBO/GA ramp (not verified)"
        )
    if est["status"] == "estimated":
        thrust_line = est["briefing"].split("): ", 1)[-1]
    else:
        thrust_line = f"unavailable ({est.get('reason') or est.get('missing_inputs')})"
    lines = [
        f"**SPAWN:** {spawn}",
        f"**TAKEOFF THRUST (simulation-grade estimate):** {thrust_line}",
        "",
    ]
    if meta.get("feasibility"):
        lines.extend([planning.assessment_line(meta["feasibility"]), ""])
        if meta["feasibility"]["status"] == "infeasible":
            lines[1] = (
                "**TAKEOFF THRUST:** withheld — the generated flight is infeasible; revise the plan first"
            )
    if flight:
        out = flight["times"]["scheduled_out"]
        est_out = flight["times"]["estimated_out"]["local"] or "n/a"
        codes = f" ({', '.join(flight['codeshares'])})" if flight["codeshares"] else ""
        lines.append(
            f"**Flight:** {flight['flight_number']}{codes} {flight['origin']['icao']} → "
            f"{flight['destination']['icao']} · real aircraft {flight['aircraft_type']} "
            f"{flight['registration']}"
        )
        lines.append(f"**Departure:** sched out {out['local']} ({out['utc']}) · est {est_out}")
    else:
        lines.append(f"**Flight:** private, callsign {meta.get('private_callsign')}")
        if syn.get("sched_out"):
            lines.append(f"**Departure:** {syn['sched_out']}")
    plan_label = (
        "SimBrief plan generated (infeasible)"
        if (meta.get("feasibility") or {}).get("status") == "infeasible"
        else "SimBrief plan confirmed"
    )
    lines.append(
        f"**{plan_label}:** generated {syn['generated_at']} · {syn['route']} · "
        f"{syn['aircraft']} · {syn['cruise']} · {syn['distance_nm']} nm · ETE {syn['ete']} · "
        f"block fuel {syn['block_fuel']} · TOW {syn['takeoff_weight']}"
    )
    count = syn.get("navlog_fix_count")
    navlog = f"{count} navlog entries" if count is not None else "navlog unavailable"
    lines.append(
        f"**Route:** {syn.get('flight_route') or 'unavailable'} "
        f"(SimBrief OFP; {navlog}). "
        "Airways/procedures can expand into navlog fixes; count does not establish route validity."
    )
    if takeoff:
        lines.append(
            f"**Takeoff:** rwy {takeoff.get('identifier')} · flaps {takeoff.get('flap_setting')} · "
            f"V1/VR/V2 {takeoff.get('speeds_v1')}/{takeoff.get('speeds_vr')}/"
            f"{takeoff.get('speeds_v2')} · bleeds {takeoff.get('bleed_setting')}"
        )
    if est["status"] == "estimated":
        lines.append(f"**Thrust method:** {est['method']}")
        lines.append("**Thrust assumptions:** " + "; ".join(est["assumptions"]))
        lines.append("**Thrust sources:** " + "; ".join(est["sources"]))
    for message in (meta.get("feasibility") or {}).get("provider_messages", []):
        lines.append(f"**SimBrief message:** {message}")
    if syn.get("arrival"):
        lines.append(f"**Estimated arrival:** {syn['arrival']} (gate arrival, UTC)")
    if meta.get("arrival_comparison"):
        lines.append(f"**Arrival target:** {meta['arrival_comparison']}")
    return "\n".join(lines)


def finalize_dispatch(
    trip: str,
    leg: str,
    revision: int = 1,
    full_thrust_n1: float | None = None,
    simulator_version: str | None = None,
) -> dict[str, Any]:
    store = _store()
    request = store.read_request(trip, leg, revision)
    if not request:
        return {"status": "missing_dispatch", "reason": "call dispatch_flight for this leg first"}
    meta = store.read_meta(trip, leg, revision)
    try:
        saved = store.read(trip, leg, revision)
        raw = store.read_raw(trip, leg, revision)
    except ValueError:
        body = fetch_sync(setting("SIMBRIEF_ALIAS"), userid=setting("SIMBRIEF_USERID"))
        normalize(body)
        raw = json.loads(body)
        generated = _utc(raw["params"]["time_generated"])
        # A browser generation must postdate its click; a manual one, the dispatch.
        since = (meta.get("generation") or {}).get("at") or meta.get("prepared_at")
        if generated < datetime.fromisoformat(since or "1970-01-01T00:00:00+00:00") - timedelta(
            minutes=1
        ):
            return {
                "status": "stale_plan",
                "reason": f"latest SimBrief plan was generated {raw['params']['time_generated']}, "
                "before this dispatch; ask the user to generate it, then retry",
            }
        planned = _utc(raw["times"]["sched_out"])
        if abs(planned - _utc(request["departure"])) > MAX_DEPARTURE_DRIFT:
            return {
                "status": "plan_mismatch",
                "reason": f"plan departs {raw['times']['sched_out']}, dispatch is "
                f"{request['departure']}; regenerate with the agreed time",
            }
        try:
            saved = store.save(trip, leg, revision, body, None)
        except ValueError as exc:
            return {"status": "plan_mismatch", "reason": str(exc)}
    data = saved["data"]
    conditions = (data.get("tlr") or {}).get("takeoff", {}).get("conditions")
    estimate = thrust.estimate_takeoff_n1(
        data["aircraft"].get("icao_code"),
        data["aircraft"].get("engines"),
        conditions,
        data.get("selected_takeoff"),
        engine_override=meta.get("engine"),
        full_thrust_n1=full_thrust_n1,
    )
    from ifdispatcher.operations import calibrated_estimate

    estimate, calibration = calibrated_estimate(
        store,
        dict(
            data, airframe_id=request.get("airframe_id"), configuration=request.get("configuration")
        ),
        meta.get("engine"),
        estimate,
        full_thrust_n1,
        simulator_version,
    )
    flight = meta.get("flight")
    if flight and flight.get("fa_flight_id"):
        try:
            flight = flights.refresh_flight(flight["fa_flight_id"]).get("data") or flight
        except ValueError:
            pass  # keep the earlier observation; its observed_at shows its age
    if flight and flight["departure_gate"] == "unavailable":
        try:
            meta["recent_gates"] = flights.recent_gates(
                flight["flight_number"], flight["origin"]["icao"]
            ).get("data")
        except ValueError:
            meta["recent_gates"] = None
    synopsis = _synopsis(raw)
    feasibility = planning.assess(raw, request)
    meta["feasibility"] = feasibility
    if request.get("arrival_target_utc") and synopsis.get("arrival"):
        delta = _utc(synopsis["arrival"]) - _utc(request["arrival_target_utc"])
        meta["arrival_comparison"] = (
            f"{request['arrival_target_utc']}; plan arrives {_relative(delta)} target"
        )
    briefing = _briefing(synopsis, flight, estimate, data.get("selected_takeoff"), meta)
    meta.update(
        briefing=briefing,
        planned_arrival=synopsis.get("arrival"),
        task_outcome="infeasible" if feasibility["status"] == "infeasible" else "briefing_ready",
    )
    store.save_meta(trip, leg, revision, meta)
    return {
        "status": "complete",
        "briefing_markdown": briefing,
        "synopsis": synopsis,
        "flight": flight,
        "recent_gates": meta.get("recent_gates"),
        "thrust": estimate,
        "snapshot": {"trip": trip, "leg": leg, "revision": revision, "sha256": saved["raw_sha256"]},
        "feasibility": feasibility,
        "calibration": calibration,
        "task_outcome": "infeasible" if feasibility["status"] == "infeasible" else "briefing_ready",
    }


def analyze_existing_plan(
    full_thrust_n1: float | None = None,
    engine: str | None = None,
    expected_origin: str | None = None,
    expected_destination: str | None = None,
    expected_flight_number: str | None = None,
) -> dict[str, Any]:
    """The user's latest SimBrief plan (already generated): thrust estimate and real-flight gate.

    Read-only: one latest-plan fetch, nothing generated or saved. The plan's flight number is
    checked against FlightAware on the plan's route; a mismatch is reported, never assumed.
    """
    body = fetch_sync(setting("SIMBRIEF_ALIAS"), userid=setting("SIMBRIEF_USERID"))
    data = normalize(body)
    raw = json.loads(body)
    conditions = (data.get("tlr") or {}).get("takeoff", {}).get("conditions")
    estimate = thrust.estimate_takeoff_n1(
        data["aircraft"].get("icao_code"),
        data["aircraft"].get("engines"),
        conditions,
        data.get("selected_takeoff"),
        engine_override=engine,
        full_thrust_n1=full_thrust_n1,
    )
    general = raw.get("general", {})
    number = f"{general.get('icao_airline') or ''}{general.get('flight_number') or ''}"
    origin, destination = data["origin"], data["destination"]
    described = {
        "origin": (expected_origin, origin),
        "destination": (expected_destination, destination),
        "flight_number": (expected_flight_number, number),
    }
    differs = {
        k: {"described": want, "latest_plan": got}
        for k, (want, got) in described.items()
        if want and want.upper().replace(" ", "") != (got or "").upper()
    }
    if differs:
        return {
            "status": "plan_mismatch",
            "reason": "the latest SimBrief plan is not the flight the user described; ask them to "
            "generate that plan (or confirm this one) before giving gate or thrust",
            "differences": differs,
            "latest_plan": _synopsis(raw),
        }
    flight, flight_note, meta = None, None, {}
    if number and general.get("icao_airline"):
        planned = _utc(raw["times"]["sched_out"])
        try:
            found = (
                flights.get_flight_by_number(number, planned.date().isoformat(), origin=origin).get(
                    "data"
                )
                or []
            )
        except ValueError as exc:
            found, flight_note = [], str(exc)
        same_route = [f for f in found if f["destination"]["icao"] == destination]
        if same_route:
            flight = min(
                same_route,
                key=lambda f: abs(_utc(f["times"]["scheduled_out"]["utc"]) - planned),
            )
            if flight["departure_gate"] == "unavailable":
                meta["recent_gates"] = flights.recent_gates(number, origin).get("data")
        else:
            flight_note = flight_note or (
                f"{number} does not operate {origin}-{destination} around the plan's departure "
                "in FlightAware data; the plan's flight number looks user-entered"
            )
    synopsis = _synopsis(raw)
    meta["feasibility"] = planning.assess(raw)
    briefing = _briefing(synopsis, flight, estimate, data.get("selected_takeoff"), meta)
    if not flight:
        briefing = briefing.replace(
            "**Flight:** private, callsign None",
            f"**Flight:** {number or 'no flight number'} (no matching real flight found)",
        )
    return {
        "status": "complete",
        "briefing_markdown": briefing,
        "flight_note": flight_note,
        "synopsis": synopsis,
        "flight": flight,
        "recent_gates": meta.get("recent_gates"),
        "thrust": estimate,
        "feasibility": meta["feasibility"],
        "task_outcome": "infeasible"
        if meta["feasibility"]["status"] == "infeasible"
        else "briefing_ready",
    }
