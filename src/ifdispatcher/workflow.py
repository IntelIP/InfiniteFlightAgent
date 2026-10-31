"""Deterministic dispatch spine called by the agent: prepare a leg, then finalize it.

dispatch_flight runs only after the user approves the exact inputs (agent interrupt_on).
finalize_dispatch fetches the latest SimBrief plan once, refuses stale or mismatched plans,
resolves thrust, refreshes the gate, and composes the briefing from data, not model text.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ifdispatcher import flights, simbrief_browser, thrust
from ifdispatcher.config import data_dir, setting
from ifdispatcher.core import Dispatch, Store, fetch_sync, normalize

MAX_DEPARTURE_DRIFT = timedelta(hours=3)


def _store() -> Store:
    return Store(data_dir())


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
    if not departure_utc:
        return {"status": "missing_input", "missing_inputs": ["departure_utc"]}
    departure = _utc(departure_utc)
    if flight:
        scheduled = _utc(flight["times"]["scheduled_out"]["utc"])
        if abs(scheduled - departure) > MAX_DEPARTURE_DRIFT:
            return {"status": "flight_mismatch", "reason": "departure differs from the schedule"}

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
    )
    store = _store()
    prepared = store.prepare(request)
    if prepared["status"] != "prepared":
        return prepared
    store.save_meta(
        trip,
        leg,
        revision,
        {
            "flight": flight,
            "engine": engine,
            "private_callsign": private_callsign,
            "prepared_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    number = flight["flight_number"] if flight else private_callsign
    airline, digits = (number[:2], number[2:]) if flight and number else (None, None)
    return {
        "status": "awaiting_simbrief_generation",
        "trip": trip,
        "leg": leg,
        "revision": revision,
        "simbrief_inputs": {
            "airline": airline,
            "flight_number": digits,
            "callsign": private_callsign,
            "departure": origin,
            "arrival": destination,
            "date": departure.strftime("%d%b%y").upper(),
            "departure_time_utc": departure.strftime("%H:%M"),
            "aircraft_type": sim_aircraft,
            "units": units.upper(),
            "passengers": passengers,
            "takeoff_performance": "enable runway analysis (TLR)",
        },
        "next_step": (
            "Call generate_in_simbrief for this leg, then finalize_dispatch. If browser "
            "generation fails, show these inputs so the user can generate manually."
        ),
        "flight": flight,
    }


def _tag(trip: str, leg: str, revision: int) -> str:
    return f"IFD_{re.sub(r'[^A-Za-z0-9]', '', trip)[:24]}_{leg}_R{revision}"


def generate_plan(trip: str, leg: str, revision: int = 1, click: bool = True) -> dict[str, Any]:
    """Fill SimBrief's dispatch form in the logged-in cloud browser and (if click) Generate once."""
    store = _store()
    request = store.read_request(trip, leg, revision)
    if not request:
        return {"status": "missing_dispatch", "reason": "call dispatch_flight for this leg first"}
    meta = store.read_meta(trip, leg, revision)
    previous = (meta.get("generation") or {}).get("status")
    if click and previous in ("clicking", "generated", "uncertain", "error"):
        return {
            "status": "already_attempted",
            "reason": f"generation already {previous} for this leg revision; finalize it, or "
            "dispatch a new revision if the user wants to regenerate",
            "generation": meta.get("generation"),
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
    if click:
        meta["generation"] = {"status": "clicking", "at": datetime.now(timezone.utc).isoformat()}
        store.save_meta(trip, leg, revision, meta)
    result = simbrief_browser.generate(fields, click, data_dir() / "screens")
    if click:
        meta["generation"] = {**meta["generation"], **result, "status": result["status"]}
        store.save_meta(trip, leg, revision, meta)
    return result


def _synopsis(raw: dict) -> dict[str, Any]:
    general, times, fuel = raw.get("general", {}), raw.get("times", {}), raw.get("fuel", {})
    weights, units = raw.get("weights", {}), raw.get("params", {}).get("units")
    altitude = general.get("initial_altitude")
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
        spawn = "Private flight: no assigned gate; choose an FBO/GA ramp (not verified)"
    if est["status"] == "estimated":
        thrust_line = est["briefing"].split("): ", 1)[-1]
    else:
        thrust_line = f"unavailable ({est.get('reason') or est.get('missing_inputs')})"
    lines = [
        f"**SPAWN:** {spawn}",
        f"**TAKEOFF THRUST (simulation-grade estimate):** {thrust_line}",
        "",
    ]
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
    lines.append(
        f"**SimBrief plan confirmed:** generated {syn['generated_at']} · {syn['route']} · "
        f"{syn['aircraft']} · {syn['cruise']} · {syn['distance_nm']} nm · ETE {syn['ete']} · "
        f"block fuel {syn['block_fuel']} · TOW {syn['takeoff_weight']}"
    )
    if takeoff:
        lines.append(
            f"**Takeoff:** rwy {takeoff.get('identifier')} · flaps {takeoff.get('flap_setting')} · "
            f"V1/VR/V2 {takeoff.get('speeds_v1')}/{takeoff.get('speeds_vr')}/"
            f"{takeoff.get('speeds_v2')} · bleeds {takeoff.get('bleed_setting')}"
        )
    return "\n".join(lines)


def finalize_dispatch(
    trip: str, leg: str, revision: int = 1, full_thrust_n1: float | None = None
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
    return {
        "status": "complete",
        "briefing_markdown": _briefing(
            synopsis, flight, estimate, data.get("selected_takeoff"), meta
        ),
        "synopsis": synopsis,
        "flight": flight,
        "recent_gates": meta.get("recent_gates"),
        "thrust": estimate,
        "snapshot": {"trip": trip, "leg": leg, "revision": revision, "sha256": saved["raw_sha256"]},
    }
