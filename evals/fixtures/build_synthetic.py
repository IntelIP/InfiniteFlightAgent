"""Deterministic GPT-6-Astra-authored scenarios; no network or model invocation."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from build_recordings import ROOT, write
import json

CLOCK = "2026-10-31T09:13:00+00:00"
NOW = datetime.fromisoformat(CLOCK)
AIRPORTS = {
    "KIAD": {
        "name": "Washington Dulles Intl",
        "city": "Washington",
        "country_code": "US",
        "timezone": "America/New_York",
    },
    "KEWR": {
        "name": "Newark Liberty Intl",
        "city": "Newark",
        "country_code": "US",
        "timezone": "America/New_York",
    },
}


def iso(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def moment(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def req(path, params, body, status=200):
    return dict(path=path, params=params, status_code=status, body=body)


def route_params(day):
    start = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo("America/New_York"))
    return dict(
        type="Airline",
        connection="nonstop",
        start=iso(max(start, NOW - timedelta(days=10))),
        end=iso(min(start + timedelta(days=1), NOW + timedelta(days=2))),
        max_pages=3,
    )


def flight(n=9101, out="2026-10-31T23:30:00Z", **overrides):
    start = moment(out)
    f = dict(
        ident=f"UAL{n}",
        ident_icao=f"UAL{n}",
        ident_iata=f"UA{n}",
        operator="UAL",
        operator_iata="UA",
        codeshares_iata=[],
        fa_flight_id=f"SYNTH-UA{n}-{out[:10]}",
        origin=dict(code_icao="KIAD", code_iata="IAD", timezone="America/New_York"),
        destination=dict(code_icao="KEWR", code_iata="EWR", timezone="America/New_York"),
        scheduled_out=out,
        estimated_out=out,
        actual_out=None,
        scheduled_off=iso(start + timedelta(minutes=15)),
        scheduled_in=iso(start + timedelta(minutes=85)),
        estimated_in=iso(start + timedelta(minutes=85)),
        gate_origin="C17",
        terminal_origin="C",
        gate_destination="C81",
        aircraft_type="B38M",
        registration="SYNTH-N9101",
        status="Scheduled",
        cancelled=False,
    )
    f.update(overrides)
    return f


def main():
    source = json.loads((ROOT / "evals/fixtures/synthetic_sources.json").read_text())
    specs = [
        (
            "normal_route",
            "Find a United flight KIAD to KEWR on October 31, 2026 after 7pm. I will fly A20N.",
            [flight()],
            "Operating equipment is B38M, simulator selection A20N; preserve both.",
        ),
        (
            "no_matches",
            "Find a United flight KIAD to KEWR on October 31, 2026 in A20N.",
            [],
            "Explicit successful empty result: do not fabricate a flight or silently dispatch.",
        ),
        (
            "missing_gate_equipment",
            "Find a United flight KIAD to KEWR on October 31, 2026 after 7pm in A20N; what gate and actual aircraft?",
            [
                flight(
                    gate_origin=None,
                    terminal_origin=" ",
                    aircraft_type=None,
                    registration=None,
                    gate_destination=None,
                )
            ],
            "Gate, terminal, registration and equipment remain unavailable. Historical gate lookup has no observations.",
        ),
        (
            "codeshare",
            "Find an Avianca-coded flight KIAD to KEWR on October 31, 2026 in A20N.",
            [flight(codeshares_iata=["AV9911"])],
            "AV9911 is marketing codeshare of operating UA9101, not a separate departure.",
        ),
        (
            "truncated",
            "List all United flights KIAD to KEWR on October 31, 2026 in A20N.",
            [flight()],
            "A next-page marker means partial results; do not claim this is an exhaustive list.",
        ),
        (
            "delayed",
            "Find United KIAD to KEWR on October 31, 2026 after 7pm in A20N; tell me scheduled and estimated departure.",
            [
                flight(
                    estimated_out="2026-11-01T01:00:00Z",
                    estimated_in="2026-11-01T02:25:00Z",
                    status="Delayed",
                )
            ],
            "Scheduled 19:30 EDT and estimated 21:00 EDT are distinct.",
        ),
        (
            "cancelled",
            "Find United KIAD to KEWR on October 31, 2026 after 7pm in A20N; is it operating?",
            [flight(cancelled=True, status="Cancelled")],
            "Only returned flight is cancelled; disclose cancellation before planning.",
        ),
        (
            "dst_fallback",
            "Show United flights KIAD to KEWR on November 1, 2026 around 1:30am in A20N; distinguish the two 1:30 times.",
            [flight(9108, "2026-11-01T05:30:00Z"), flight(9109, "2026-11-01T06:30:00Z")],
            "25-hour local date; 01:30 EDT and 01:30 EST differ by one hour. Scheduled arrival crosses offset change.",
        ),
        (
            "utc_midnight",
            "Find United KIAD to KEWR on October 31, 2026 at about 11:30pm in A20N.",
            [flight(9110, "2026-11-01T03:30:00Z")],
            "UTC date November 1 belongs to October 31 departure local date.",
        ),
        (
            "flight_number",
            "Look up UA9111 from KIAD on October 31, 2026; use A20N in the simulator.",
            [flight(9111)],
            "Designator lookup returns a raw flights array, not route segments.",
        ),
        (
            "departure_board",
            "Show departures from KIAD on October 31, 2026 between 7pm and 9pm local, any airline, to KEWR; I will fly A20N.",
            [
                flight(9112),
                flight(9113, "2026-11-01T01:00:00Z"),
                flight(9114, "2026-10-31T22:55:00Z"),
            ],
            "Board taxi padding includes rows before start and at exclusive end; only UA9112 is inside the gate-time window.",
        ),
        (
            "api_error",
            "Find United KIAD to KEWR on October 31, 2026 in A20N.",
            [],
            "Synthetic HTTP 503: report provider failure, never misstate it as a successful empty schedule.",
        ),
    ]
    cases = []
    for i, (label, prompt, rows, note) in enumerate(specs, 1):
        cid = f"SYNTH-{i:03d}"
        day = "2026-11-01" if label == "dst_fallback" else "2026-10-31"
        requests = [req(f"/airports/{code}", {}, meta) for code, meta in AIRPORTS.items()]
        action = "search_route"
        if label == "flight_number":
            action = "lookup_flight_number"
            start = datetime(2026, 10, 31, tzinfo=timezone.utc) - timedelta(hours=14)
            for ident in ("UA9111", "UAL9111"):
                requests.append(
                    req(
                        f"/flights/{ident}",
                        dict(
                            ident_type="designator",
                            start=iso(start),
                            end=iso(start + timedelta(hours=52)),
                            max_pages=2,
                        ),
                        dict(flights=rows, num_pages=1, links=None),
                    )
                )
        elif label == "departure_board":
            action = "airport_departures"
            requests.append(
                req(
                    "/airports/KIAD/flights/scheduled_departures",
                    dict(
                        type="Airline",
                        start="2026-10-31T22:45:00Z",
                        end="2026-11-01T02:00:00Z",
                        max_pages=3,
                    ),
                    dict(scheduled_departures=rows, num_pages=1, links=None),
                )
            )
        else:
            body = dict(
                flights=[dict(segments=[f]) for f in rows],
                num_pages=3 if label == "truncated" else 1,
                links={"next": "/synthetic-only/unavailable-next-page"}
                if label == "truncated"
                else None,
            )
            requests.append(
                req(
                    "/airports/KIAD/flights/to/KEWR",
                    route_params(day),
                    {"error": "Synthetic upstream unavailable"} if label == "api_error" else body,
                    503 if label == "api_error" else 200,
                )
            )
        for f in rows:
            requests.append(
                req("/flights/" + f["fa_flight_id"], {}, dict(flights=[f], num_pages=1, links=None))
            )
        if label == "missing_gate_equipment":
            for ident in ("UA9101", "UAL9101"):
                requests.append(
                    req(
                        "/flights/" + ident,
                        dict(
                            ident_type="designator",
                            start=iso(NOW - timedelta(days=10) + timedelta(minutes=5)),
                            end=iso(NOW),
                            max_pages=2,
                        ),
                        dict(flights=[], num_pages=1, links=None),
                    )
                )
        fixture = f"evals/fixtures/synthetic/{cid}.json"
        write(
            ROOT / fixture,
            dict(
                schema_version=1,
                kind="synthetic",
                clock=CLOCK,
                provenance=dict(
                    generator="GPT-6-Astra",
                    sources=source,
                    description="Invented test scenario, not a live schedule. Normalized capture supplies field-shape inspiration and airport names only. "
                    + note,
                    metadata="America/New_York test timezone follows tests/test_flights.py; flight numbers, IDs, dates, gates, registrations, equipment and statuses are invented.",
                ),
                requests=requests,
            ),
        )
        cases.append(
            dict(
                id=cid,
                category="departure_window"
                if label == "departure_board"
                else "flight_number"
                if label == "flight_number"
                else "edge_cases",
                prompt=prompt,
                followups={
                    "approve_dispatch": "yes, go ahead",
                    "engine_or_livery": "United livery",
                },
                expected=dict(
                    first_action=action,
                    clarify_topics=[],
                    legs=[dict(origin="KIAD", destination="KEWR")],
                    multi_leg=False,
                    international=False,
                    real_flight_expected=True,
                    disallow_dispatch=label in ("no_matches", "api_error", "cancelled"),
                    aircraft_icao="A20N",
                    thrust_supported=True,
                    date_in_aeroapi_window=True,
                    must_not=[
                        "invent_flight_number",
                        "generate_before_approval",
                        "treat_sim_aircraft_as_real_equipment",
                    ],
                ),
                notes="SYNTHETIC / " + label + ": " + note,
                fixture=fixture,
            )
        )
    (ROOT / "evals/fixtures/synthetic_cases.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in cases)
    )
    print(f"Generated {len(cases)} synthetic cases")


if __name__ == "__main__":
    main()
