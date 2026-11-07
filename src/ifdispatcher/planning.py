"""Deterministic arrival planning and checks on the retained SimBrief solution.

These checks establish consistency of the supplied plan, not real-world airworthiness or
Infinite Flight performance. Missing simulator configuration remains unknown.
"""

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def duration(value: str) -> timedelta:
    parts = str(value).split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        raise ValueError("invalid_duration: use HH:MM or HH:MM:SS")
    hours, minutes, *seconds = map(int, parts)
    if minutes >= 60 or (seconds and seconds[0] >= 60):
        raise ValueError("invalid_duration: minutes and seconds must be below 60")
    result = timedelta(hours=hours, minutes=minutes, seconds=seconds[0] if seconds else 0)
    if not timedelta(0) < result <= timedelta(days=3):
        raise ValueError("invalid_duration: duration must be positive and at most 72 hours")
    return result


def arrival_plan(
    arrival_local: str,
    destination_timezone: str,
    block_time: str,
    duration_source: str,
    origin_timezone: str | None = None,
) -> dict:
    if not duration_source.strip():
        raise ValueError("duration_source_required: identify the plan or estimate for block time")
    local = datetime.fromisoformat(arrival_local)
    if local.tzinfo is not None:
        raise ValueError(
            "invalid_arrival: supply local date and time without an offset; timezone is separate"
        )
    tz = ZoneInfo(destination_timezone)
    candidates = {
        local.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc)
        for fold in (0, 1)
        if local.replace(tzinfo=tz, fold=fold)
        .astimezone(timezone.utc)
        .astimezone(tz)
        .replace(tzinfo=None)
        == local
    }
    if len(candidates) != 1:
        raise ValueError(
            "ambiguous_arrival: local time is ambiguous or nonexistent; choose a different time"
        )
    arrival = candidates.pop()
    departure = arrival - duration(block_time)
    return {
        "status": "estimated",
        "arrival_utc": arrival.isoformat(),
        "arrival_local": arrival.astimezone(tz).isoformat(),
        "departure_utc": departure.isoformat(),
        "departure_local": departure.astimezone(ZoneInfo(origin_timezone)).isoformat()
        if origin_timezone
        else None,
        "block_time": block_time,
        "duration_source": duration_source,
        "note": "Planning estimate using gate-to-gate block time; recheck against the generated plan and winds.",
    }


def assess(raw: dict, request: dict | None = None) -> dict:
    request = request or {}
    fuel, weights, general = (raw.get(k) or {} for k in ("fuel", "weights", "general"))
    units = (raw.get("params") or {}).get("units")
    fields = {
        k: number(fuel.get(k))
        for k in (
            "plan_ramp",
            "plan_takeoff",
            "min_takeoff",
            "plan_landing",
            "max_tanks",
            "reserve",
            "alternate_burn",
            "contingency",
            "enroute_burn",
            "extra_required",
        )
    }
    messages = []
    for key in ("sys_rmk", "dx_rmk"):
        value = general.get(key) or []
        messages.extend([value] if isinstance(value, str) else [str(v) for v in value])
    problems = []

    def exceeds(value, limit, description):
        if value is not None and limit is not None and value > limit:
            problems.append(description)

    exceeds(
        fields["plan_ramp"], fields["max_tanks"], "Planned ramp fuel exceeds SimBrief tank capacity"
    )
    exceeds(
        fields["min_takeoff"],
        fields["plan_takeoff"],
        "Takeoff fuel is below SimBrief's minimum requirement",
    )
    if fields["plan_landing"] is not None and fields["plan_landing"] < 0:
        problems.append("Predicted landing fuel is negative")
    if fields["reserve"] is not None and fields["alternate_burn"] is not None:
        exceeds(
            fields["reserve"] + fields["alternate_burn"],
            fields["plan_landing"],
            "Landing fuel is below the planned alternate and final reserve requirement",
        )
    for estimated, maximum, label in (
        ("est_tow", "max_tow", "Takeoff weight"),
        ("est_ldw", "max_ldw", "Landing weight"),
        ("est_zfw", "max_zfw", "Zero-fuel weight"),
    ):
        exceeds(
            number(weights.get(estimated)),
            number(weights.get(maximum)),
            f"{label} exceeds the plan's limit",
        )
    if (
        request.get("passengers") is not None
        and number(weights.get("pax_count")) != request["passengers"]
    ):
        problems.append("Generated passenger count differs from the agreed load")
    warnings = [
        m for m in messages if any(w in m.upper() for w in ("EXCEED", "INSUFFICIENT", "ERROR"))
    ]
    problems.extend(warnings)
    capacity = number(request.get("simulator_capacity"))
    source = request.get("capacity_source")
    if capacity is not None and source:
        exceeds(
            fields["plan_ramp"],
            capacity,
            "Planned ramp fuel exceeds the supplied simulator capacity",
        )
    required = (
        "plan_ramp",
        "plan_takeoff",
        "min_takeoff",
        "plan_landing",
        "max_tanks",
        "reserve",
        "alternate_burn",
    )
    missing = [f"fuel.{k}" for k in required if fields[k] is None]
    status = "infeasible" if problems else "unknown" if missing else "plan_checks_passed"
    simulator_status = (
        "unknown"
        if capacity is None or not source
        else (
            "capacity_exceeded"
            if fields["plan_ramp"] is not None and fields["plan_ramp"] > capacity
            else "capacity_checked"
            if fields["plan_ramp"] is not None
            else "unknown"
        )
    )
    return {
        "status": status,
        "units": units,
        "fuel": fields,
        "problems": problems,
        "provider_messages": messages,
        "missing_inputs": missing,
        "configuration": request.get("configuration")
        or "SimBrief profile; simulator configuration not verified",
        "airframe_id": (raw.get("aircraft") or {}).get("internal_id"),
        "simulator_status": simulator_status,
        "simulator_capacity": capacity,
        "capacity_source": source,
        "note": "Plan checks and supplied simulator capacity only; this does not establish legal reserves or simulator performance.",
    }


def assessment_line(result: dict) -> str:
    status = result["status"]
    if status == "infeasible":
        return "**FLIGHT FEASIBILITY: INFEASIBLE** — " + "; ".join(result["problems"])
    if status == "unknown":
        return "**FLIGHT FEASIBILITY: UNKNOWN** — missing plan data; simulator configuration not verified"
    return "**FLIGHT FEASIBILITY:** plan checks passed; simulator performance remains unverified"
