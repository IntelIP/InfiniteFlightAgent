"""FlightAware AeroAPI v4 research: real flights, departure windows, gates, equipment.

Plan and limits: docs/implementation/flight-tools-plan.md. Read-only GETs, max 3 result sets
per call, 60 s flight cache, seven-day persistent airport metadata cache, no polling. Values are FlightAware observations, never
simulator positions; a missing gate or aircraft stays "unavailable".
"""

import json
import re
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ifdispatcher.config import require_paid_operations, setting

BASE = "https://aeroapi.flightaware.com/aeroapi"
SOURCE = "FlightAware AeroAPI v4"
MAX_PAGES = 3
CACHE_TTL = 60.0
WINDOW_PAST, WINDOW_FUTURE = timedelta(days=10), timedelta(days=2)
TIME_FIELDS = (
    "scheduled_out",
    "estimated_out",
    "actual_out",
    "scheduled_off",
    "scheduled_in",
    "estimated_in",
)
CARGO_OPERATORS = {"FDX", "UPS", "MTN", "GTI", "ABX", "ATN", "CKS", "PAC", "GEC", "CLX"}

_cache: dict[str, tuple[float, dict]] = {}
usage = {"requests": 0, "result_sets": 0, "cost_milliusd": 0, "cache_hits": 0}
RATE_LIMIT = 10  # Personal tier: 10 result sets per minute
_recent: list[tuple[float, int]] = []  # (monotonic time, result sets) in the last minute


# Published list rates, checked 2026-11-01: flightaware.com/commercial/aeroapi/.
# Integer thousandths of a dollar avoid rounding while accumulating small charges.
def price_milliusd(path: str) -> int:
    if re.fullmatch(r"/airports/[^/]+/flights/to/[^/]+", path):
        return 50
    if re.fullmatch(r"/airports/[^/]+", path):
        return 15
    if re.fullmatch(r"/flights/[^/]+", path) or re.fullmatch(
        r"/airports/[^/]+/flights/(scheduled_departures|departures)", path
    ):
        return 5
    raise ValueError(f"unpriced_endpoint: {path}")


def _airport_cache_path(path: str) -> Path | None:
    if not re.fullmatch(r"/airports/[A-Z0-9]{3,4}", path):
        return None
    directory = setting("IFD_AIRPORT_CACHE_DIR")
    if directory == "disabled":
        return None
    root = (
        Path(directory) if directory else Path.home() / ".cache/InfiniteFlightDispatcher/airports"
    )
    return root / (path.rsplit("/", 1)[1] + ".json")


def _airport_cached(path: str) -> dict | None:
    file = _airport_cache_path(path)
    if file is None:
        return None
    try:
        entry = json.loads(file.read_text())
        age = time.time() - entry["saved_at"]
        if 0 <= age < 7 * 86400 and isinstance(entry["body"], dict):
            return entry["body"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _save_airport(path: str, data: dict) -> None:
    file = _airport_cache_path(path)
    if file is None:
        return
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", dir=file.parent, delete=False) as temp:
            json.dump({"saved_at": time.time(), "body": data}, temp)
        Path(temp.name).replace(file)
    except OSError:
        pass  # An optional metadata cache must not break flight research.


def _wait_for_rate_limit(sets: int) -> None:
    """Pace calls under the per-minute result-set limit instead of failing with 429."""
    while True:
        now = time.monotonic()
        _recent[:] = [(t, n) for t, n in _recent if now - t < 60]
        if sum(n for _, n in _recent) + sets <= RATE_LIMIT or not _recent:
            return
        time.sleep(min(60.0, 60 - (now - _recent[0][0]) + 0.5))


def _api_key() -> str:
    key = setting("AEROAPI_KEY")
    if not key:
        raise ValueError("missing_configuration: AEROAPI_KEY not set (environment or .env)")
    return key


def _get(path: str, params: dict | None = None, transport=None) -> dict:
    query = {k: v for k, v in (params or {}).items() if v is not None}
    cache_key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(query.items()))
    hit = _cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        usage["cache_hits"] += 1
        return hit[1]
    stored = _airport_cached(path) if not query and transport is None else None
    if stored is not None:
        usage["cache_hits"] += 1
        return stored
    rate = price_milliusd(path)
    require_paid_operations()
    _wait_for_rate_limit(int(query.get("max_pages") or 1))
    try:
        with httpx.Client(timeout=30, transport=transport) as client:
            response = client.get(BASE + path, params=query, headers={"x-apikey": _api_key()})
    except httpx.RequestError as exc:
        raise ValueError("network_error: AeroAPI request failed; no retry performed") from exc
    if response.status_code == 401:
        raise ValueError("unauthorized: invalid key or endpoint above the Personal tier")
    if response.status_code == 429:
        raise ValueError("rate_limited: AeroAPI rate limit; wait before retrying")
    if response.status_code >= 400:
        raise ValueError(f"http_error: AeroAPI returned {response.status_code}")
    data = response.json()
    usage["requests"] += 1
    usage["result_sets"] += int(data.get("num_pages") or 1)
    usage["cost_milliusd"] += rate * int(data.get("num_pages") or 1)
    _recent.append((time.monotonic(), int(data.get("num_pages") or 1)))
    _cache[cache_key] = (time.monotonic(), data)
    if not query and transport is None:
        _save_airport(path, data)
    return data


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _clip(start: datetime, end: datetime) -> tuple[datetime, datetime] | None:
    """Trim a query to AeroAPI's window (10 days back, 2 days ahead); None if no overlap."""
    now = datetime.now(timezone.utc)
    start, end = max(start, now - WINDOW_PAST), min(end, now + WINDOW_FUTURE)
    return (start, end) if start < end else None


OUTSIDE = (
    "outside_window: AeroAPI covers 10 days back to 2 days ahead; "
    "no live schedule or gate is available for this date"
)


def airport_timezone(airport: str) -> str:
    data = _get(f"/airports/{airport.upper()}")
    tz = data.get("timezone")
    if not tz:
        raise ValueError(f"unknown_airport: no timezone for {airport}")
    return tz


def airport_name(airport: str) -> str:
    """FlightAware's name for an airport code, e.g. "St. John's Int'l (St. John's, CA)"."""
    data = _get(f"/airports/{airport.upper()}")
    name = data.get("name")
    if not name:
        raise ValueError(f"unknown_airport: FlightAware has no airport {airport}")
    place = ", ".join(x for x in (data.get("city"), data.get("country_code")) if x)
    return f"{name} ({place})" if place else name


def local_time(value: str, airport: str) -> str:
    """A UTC time as local time at an airport, e.g. "2026-11-02 08:20 EST"."""
    return _local(value, airport_timezone(airport)) or value


def _local(value: str | None, tz: str | None) -> str | None:
    moment = _parse(value)
    if not moment or not tz:
        return None
    return moment.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M %Z")


def normalize_flight(f: dict, observed_at: str) -> dict[str, Any]:
    origin, dest = f.get("origin") or {}, f.get("destination") or {}
    out = _parse(f.get("scheduled_out"))
    now = datetime.now(timezone.utc)
    temporal = (
        "historical"
        if f.get("actual_in") or f.get("actual_on")
        else "current"
        if f.get("actual_out") or (out and abs(out - now) < timedelta(hours=3))
        else "future_schedule"
    )
    times = {}
    for name in TIME_FIELDS:
        tz = (dest if name.endswith("_in") else origin).get("timezone")
        times[name] = {"utc": f.get(name), "local": _local(f.get(name), tz)}

    def state(value):
        value = value.strip() if isinstance(value, str) else value
        return value if value not in (None, "") else "unavailable"

    return {
        "flight_number": f.get("ident_iata") or f.get("ident"),
        "ident_icao": f.get("ident_icao"),
        "operator": f.get("operator_iata") or f.get("operator"),
        "codeshares": f.get("codeshares_iata") or [],
        "fa_flight_id": f.get("fa_flight_id"),
        "origin": {"icao": origin.get("code_icao"), "iata": origin.get("code_iata")},
        "destination": {"icao": dest.get("code_icao"), "iata": dest.get("code_iata")},
        "times": times,
        "departure_gate": state(f.get("gate_origin")),
        "departure_terminal": state(f.get("terminal_origin")),
        "arrival_gate": state(f.get("gate_destination")),
        "aircraft_type": state(f.get("aircraft_type")),
        "registration": state(f.get("registration")),
        "status": f.get("status"),
        "cancelled": bool(f.get("cancelled")),
        "temporal_class": temporal,
        "observed_at": observed_at,
        "note": "FlightAware observation; gate and aircraft for future flights may change",
    }


def _envelope(status: str, data=None, refs=None, **extra) -> dict[str, Any]:
    return {
        "status": status,
        "data": data,
        "source_refs": refs or [],
        "observed_at": _iso(datetime.now(timezone.utc)),
        **extra,
    }


def _keep(f: dict, airline: str | None, include_cargo: bool) -> bool:
    operator = (f.get("operator") or "").upper()
    if not include_cargo and (operator in CARGO_OPERATORS or not f.get("scheduled_out")):
        return False
    if airline:
        code = airline.upper()
        numbers = [f.get("ident_iata") or "", f.get("ident") or ""] + list(
            f.get("codeshares_iata") or []
        )
        if not any(n.upper().startswith(code) for n in numbers) and operator != code:
            return False
    return True


def _day_bounds(airport: str, local_date: str) -> tuple[datetime, datetime, str]:
    tz = airport_timezone(airport)
    day = date.fromisoformat(local_date)
    start = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(tz))
    return start, start + timedelta(days=1), tz


def find_route_flights(
    origin: str,
    destination: str,
    local_date: str,
    airline: str | None = None,
    include_cargo: bool = False,
) -> dict[str, Any]:
    """Real nonstop flights origin -> destination on the origin's local date."""
    origin, destination = origin.upper(), destination.upper()
    window = _clip(*_day_bounds(origin, local_date)[:2])
    if not window:
        return _envelope("unsupported_window", reason=OUTSIDE)
    start, end = window
    path = f"/airports/{origin}/flights/to/{destination}"
    params = {
        "type": "Airline",
        "connection": "nonstop",
        "start": _iso(start),
        "end": _iso(end),
        "max_pages": MAX_PAGES,
    }
    data = _get(path, params)
    observed = _iso(datetime.now(timezone.utc))
    segments = [s for f in data.get("flights", []) for s in (f.get("segments") or [])]
    kept = [s for s in segments if _keep(s, airline, include_cargo)]
    kept.sort(key=lambda s: s.get("scheduled_out") or "")
    flights = [normalize_flight(s, observed) for s in kept]
    return _envelope(
        "ok" if flights else "no_flights",
        flights,
        [f"{SOURCE} GET {path} {params['start']}..{params['end']}"],
        truncated=bool(data.get("links")),
    )


def find_airport_departures(
    airport: str,
    local_date: str,
    start_local: str,
    end_local: str,
    airline: str | None = None,
    destination: str | None = None,
    include_cargo: bool = False,
) -> dict[str, Any]:
    """Flights leaving the gate at `airport` between two local times (window <= 3 h)."""
    airport = airport.upper()
    tz = ZoneInfo(airport_timezone(airport))
    day = date.fromisoformat(local_date)

    def at(hhmm: str) -> datetime:
        hour, minute = (int(x) for x in hhmm.split(":"))
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)

    start, end = at(start_local), at(end_local)
    if end <= start:
        end += timedelta(days=1)
    if end - start > timedelta(hours=3):
        return _envelope("missing_input", missing_inputs=["window must be 3 hours or less"])
    if not _clip(start, end):
        return _envelope("unsupported_window", reason=OUTSIDE)
    # Boards filter on takeoff time; widen for taxi, then keep gate departures in the window.
    future = end > datetime.now(timezone.utc)
    board = "scheduled_departures" if future else "departures"
    path = f"/airports/{airport}/flights/{board}"
    params = {
        "type": None if airline else "Airline",
        "airline": airline.upper() if airline and len(airline) == 3 else None,
        "start": _iso(start - timedelta(minutes=15)),
        "end": _iso(end + timedelta(minutes=60)),
        "max_pages": MAX_PAGES,
    }
    if params["airline"] is None:
        params["type"] = "Airline"
    data = _get(path, params)
    observed = _iso(datetime.now(timezone.utc))
    rows = data.get(board, [])
    kept = []
    for f in rows:
        out = _parse(f.get("scheduled_out"))
        dest = (f.get("destination") or {}).get("code_icao")
        if not out or not start <= out < end:
            continue
        if destination and dest != destination.upper():
            continue
        if _keep(f, airline if airline and len(airline) == 2 else None, include_cargo):
            kept.append(f)
    kept.sort(key=lambda f: f.get("scheduled_out") or "")
    flights = [normalize_flight(f, observed) for f in kept]
    return _envelope(
        "ok" if flights else "no_flights",
        flights,
        [f"{SOURCE} GET {path} {params['start']}..{params['end']} (filtered on scheduled_out)"],
        truncated=bool(data.get("links")),
    )


def get_flight_by_number(
    flight_number: str, local_date: str | None = None, origin: str | None = None
) -> dict[str, Any]:
    """All occurrences of a flight number within the AeroAPI window (or one local date)."""
    ident = flight_number.upper().replace(" ", "")
    now = datetime.now(timezone.utc)
    if local_date:
        day = date.fromisoformat(local_date)
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - timedelta(hours=14)
        window = _clip(start, start + timedelta(hours=52))
        if not window:
            return _envelope("unsupported_window", reason=OUTSIDE)
        start, end = window
    else:
        start, end = now - timedelta(days=1), now + WINDOW_FUTURE
    path = f"/flights/{ident}"
    params = {"ident_type": "designator", "start": _iso(start), "end": _iso(end), "max_pages": 2}
    data = _get(path, params)
    observed = _iso(now)
    rows = data.get("flights", [])
    if origin:
        rows = [f for f in rows if (f.get("origin") or {}).get("code_icao") == origin.upper()]
    rows.sort(key=lambda f: f.get("scheduled_out") or "")
    flights = [normalize_flight(f, observed) for f in rows]
    return _envelope(
        "ok" if flights else "no_flights",
        flights,
        [f"{SOURCE} GET {path} {params['start']}..{params['end']}"],
    )


def refresh_flight(fa_flight_id: str) -> dict[str, Any]:
    """Re-read one flight (gate, aircraft, estimated times) close to departure."""
    path = f"/flights/{fa_flight_id}"
    data = _get(path)
    rows = data.get("flights", [])
    observed = _iso(datetime.now(timezone.utc))
    if not rows:
        return _envelope("no_flights", None, [f"{SOURCE} GET {path}"])
    return _envelope("ok", normalize_flight(rows[0], observed), [f"{SOURCE} GET {path}"])


def recent_gates(flight_number: str, origin: str, limit: int = 5) -> dict[str, Any]:
    """Departure gates of the most recent completed occurrences of a flight (last 10 days).

    Historical context for a future flight whose gate is not assigned yet; never an assignment.
    """
    ident = flight_number.upper().replace(" ", "")
    now = datetime.now(timezone.utc)
    path = f"/flights/{ident}"
    params = {
        "ident_type": "designator",
        "start": _iso(now - WINDOW_PAST + timedelta(minutes=5)),
        "end": _iso(now),
        "max_pages": 2,
    }
    data = _get(path, params)
    rows = [
        f
        for f in data.get("flights", [])
        if (f.get("origin") or {}).get("code_icao") == origin.upper()
        and f.get("actual_out")
        and (f.get("gate_origin") or "").strip()
    ]
    rows.sort(key=lambda f: f.get("scheduled_out") or "", reverse=True)
    recent = [
        {
            "date_local": (
                _local(f.get("scheduled_out"), (f.get("origin") or {}).get("timezone")) or ""
            )[:10],
            "gate": f["gate_origin"].strip(),
            "terminal": (f.get("terminal_origin") or "").strip() or None,
            "aircraft_type": (f.get("aircraft_type") or "").strip() or None,
            "registration": f.get("registration"),
        }
        for f in rows[:limit]
    ]
    return _envelope(
        "ok" if recent else "no_flights",
        {"most_recent": recent[0] if recent else None, "recent": recent},
        [f"{SOURCE} GET {path} {params['start']}..{params['end']} (completed occurrences)"],
        note="Historical gates of completed flights; not an assignment for an upcoming flight",
    )
