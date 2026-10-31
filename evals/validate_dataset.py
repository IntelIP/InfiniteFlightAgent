#!/usr/bin/env python3
"""Validate evals/dispatch_prompts.jsonl (standard library only).

Checks schema, enums, exact count, id sequence, prompt uniqueness and
near-duplicates, category quotas, and internal consistency between the
prompt-derived expectations (legs, aircraft, date window, first action,
clarification topics, and must_not rules). Exits 1 on any problem.

Conventions encoded here:
- aircraft_icao reflects the user's first message only; a sim aircraft chosen
  later in followups does not change it.
- real_flight_expected is True for a neutral route request (the default
  airline workflow), False for private/GA, None only when the user is unsure.
  A multi-leg case mixing airline and private legs uses True and says so in notes.
- international is None whenever any leg destination is unknown.

Usage: python3 evals/validate_dataset.py [path]
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / "dispatch_prompts.jsonl"
EXPECTED_COUNT = 100

QUOTAS = {
    "domestic_specific": 12,
    "domestic_vague": 8,
    "international_specific": 12,
    "international_vague": 8,
    "multi_leg": 15,
    "not_sure": 10,
    "private_ga": 8,
    "flight_number": 7,
    "departure_window": 5,
    "unsupported_aircraft": 5,
    "edge_cases": 10,
}
TOPICS = {
    "origin",
    "destination",
    "date",
    "time",
    "airline",
    "aircraft",
    "engine_or_livery",
    "private_or_airline",
    "passengers_or_load",
    "approve_dispatch",
}
FIRST_ACTIONS = {
    "ask_clarification",
    "search_route",
    "lookup_flight_number",
    "airport_departures",
    "explain_limitation",
}
MUST_NOT = {
    "invent_flight_number",
    "assume_date",
    "assume_aircraft",
    "assume_origin",
    "generate_before_approval",
    "claim_gate_for_far_future",
    "compute_thrust_for_unsupported",
    "treat_sim_aircraft_as_real_equipment",
    "mix_up_legs",
}
SUPPORTED_AIRCRAFT = {"A20N", "A21N", "B38M"}
TOP_KEYS = {"id", "category", "prompt", "followups", "expected", "notes"}
EXPECTED_KEYS = {
    "first_action",
    "clarify_topics",
    "legs",
    "multi_leg",
    "international",
    "real_flight_expected",
    "aircraft_icao",
    "thrust_supported",
    "date_in_aeroapi_window",
    "must_not",
}
ICAO_AIRPORT = re.compile(r"^[A-Z][A-Z0-9]{3}$")
ICAO_TYPE = re.compile(r"^[A-Z][A-Z0-9]{1,3}$")
# US ICAO prefixes: contiguous US (K), Alaska (PA), Hawaii (PH), other Pacific US (PG, PF, PO, PP).
US_PREFIXES = ("K", "PA", "PH", "PG", "PF", "PO", "PP")
FLIGHT_NUMBER = re.compile(
    r"\b[A-Za-z]{2}\s?\d{1,4}\b|\b(United|Delta|American|Lufthansa|Southwest)\s+\d{1,4}\b", re.I
)
RELATIVE_DATE = re.compile(
    r"\b(tonight|today|tomorrow|yesterday|this (morning|afternoon|evening|weekend)|"
    r"next (week|month|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"last (monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"saturday|sunday|halloween|christmas eve|in the next hour)\b",
    re.I,
)
NEAR_DUP_RATIO = 0.85
MIN_DATE_CLARIFY = 12
MIN_RELATIVE_DATE = 10


def is_us(code: str) -> bool:
    return code.startswith(US_PREFIXES)


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def check_row(row: dict, errs: list[str]) -> None:
    rid = row.get("id", "?")

    def err(msg: str) -> None:
        errs.append(f"{rid}: {msg}")

    if set(row) != TOP_KEYS:
        err(f"top-level keys {sorted(row)} != {sorted(TOP_KEYS)}")
        return
    cat = row["category"]
    if cat not in QUOTAS:
        err(f"unknown category {cat!r}")
    for key in ("prompt", "notes"):
        if not isinstance(row[key], str) or not row[key].strip():
            err(f"{key} must be a non-empty string")

    fu = row["followups"]
    if not isinstance(fu, dict):
        err("followups must be an object")
        fu = {}
    for topic, answer in fu.items():
        if topic not in TOPICS:
            err(f"followup topic {topic!r} not allowed")
        if not isinstance(answer, str) or not answer.strip():
            err(f"followup {topic!r} answer must be a non-empty string")

    exp = row["expected"]
    if not isinstance(exp, dict) or set(exp) != EXPECTED_KEYS:
        err(
            f"expected keys {sorted(exp) if isinstance(exp, dict) else exp} != {sorted(EXPECTED_KEYS)}"
        )
        return

    first = exp["first_action"]
    if first not in FIRST_ACTIONS:
        err(f"first_action {first!r} invalid")

    clarify = exp["clarify_topics"]
    if not isinstance(clarify, list) or len(set(clarify)) != len(clarify):
        err("clarify_topics must be a list without duplicates")
        clarify = []
    for topic in clarify:
        if topic not in TOPICS:
            err(f"clarify topic {topic!r} not allowed")
        elif topic not in fu:
            err(f"clarify topic {topic!r} has no scripted followup answer")

    legs = exp["legs"]
    if not isinstance(legs, list) or not 1 <= len(legs) <= 4:
        err("legs must be a list of 1-4 legs")
        legs = []
    for i, leg in enumerate(legs):
        if not isinstance(leg, dict) or set(leg) != {"origin", "destination"}:
            err(f"leg {i} must have exactly origin and destination")
            continue
        for k in ("origin", "destination"):
            v = leg[k]
            if v is not None and (not isinstance(v, str) or not ICAO_AIRPORT.match(v)):
                err(f"leg {i} {k} {v!r} is not an ICAO code or null")
        if leg["origin"] and leg["origin"] == leg["destination"]:
            err(f"leg {i} origin equals destination")
        if i and isinstance(legs[i - 1], dict):
            prev_dest, this_origin = legs[i - 1].get("destination"), leg["origin"]
            if prev_dest and this_origin and prev_dest != this_origin:
                err(f"leg {i} origin {this_origin} does not continue from {prev_dest}")

    multi = exp["multi_leg"]
    if not isinstance(multi, bool) or multi != (len(legs) > 1):
        err("multi_leg must equal len(legs) > 1")
    if cat == "multi_leg" and not 2 <= len(legs) <= 4:
        err("multi_leg category needs 2-4 legs")
    if cat != "multi_leg" and len(legs) != 1:
        err("non-multi_leg categories must have exactly one leg")

    intl = exp["international"]
    dests_known = bool(legs) and all(
        isinstance(leg, dict) and leg.get("destination") for leg in legs
    )
    if not dests_known:
        if intl is not None:
            err("international must be null when any destination is unknown")
    else:
        codes = [leg[k] for leg in legs for k in ("origin", "destination") if leg.get(k)]
        derived = any(not is_us(c) for c in codes)
        if intl is not derived:
            err(f"international {intl!r} inconsistent with airports {codes}")
    if cat.startswith("domestic") and intl is True:
        err("domestic category marked international")
    if cat.startswith("international") and intl is False:
        err("international category marked domestic")

    real = exp["real_flight_expected"]
    if real not in (True, False, None):
        err("real_flight_expected must be true, false or null")
    if cat == "private_ga" and real is not False:
        err("private_ga cases must have real_flight_expected false")

    ac = exp["aircraft_icao"]
    if ac is not None and (not isinstance(ac, str) or not ICAO_TYPE.match(ac)):
        err(f"aircraft_icao {ac!r} invalid")
    ts = exp["thrust_supported"]
    want_ts = None if ac is None else ac in SUPPORTED_AIRCRAFT
    if ts is not want_ts:
        err(f"thrust_supported {ts!r} inconsistent with aircraft {ac!r}")
    if cat == "unsupported_aircraft" and ts is not False:
        err("unsupported_aircraft cases need a specified unsupported aircraft")

    win = exp["date_in_aeroapi_window"]
    if win not in (True, False, None):
        err("date_in_aeroapi_window must be true, false or null")

    must = exp["must_not"]
    if not isinstance(must, list) or len(set(must)) != len(must):
        err("must_not must be a list without duplicates")
        must = []
    for m in must:
        if m not in MUST_NOT:
            err(f"must_not value {m!r} not allowed")
    rules = [
        ("date" in clarify, "assume_date"),
        ("aircraft" in clarify, "assume_aircraft"),
        ("origin" in clarify, "assume_origin"),
        (ts is False, "compute_thrust_for_unsupported"),
        (multi is True, "mix_up_legs"),
        (win is False and real is not False, "claim_gate_for_far_future"),
        (real is True and ac is not None, "treat_sim_aircraft_as_real_equipment"),
        (True, "generate_before_approval"),
    ]
    for condition, value in rules:
        if condition and value not in must:
            err(f"must_not is missing {value!r}")
    if "compute_thrust_for_unsupported" in must and ts is not False:
        err(
            "compute_thrust_for_unsupported listed but aircraft is not a specified unsupported type"
        )
    if "mix_up_legs" in must and not multi:
        err("mix_up_legs listed for a single-leg case")

    first_leg = legs[0] if legs and isinstance(legs[0], dict) else {}
    if first == "search_route":
        if not (first_leg.get("origin") and first_leg.get("destination")):
            err("search_route needs a known first-leg origin and destination")
        if win is not True or real is False:
            err("search_route needs an in-window date and an airline flight")
    elif first == "lookup_flight_number":
        if win is not True or real is False:
            err("lookup_flight_number needs an in-window date and an airline flight")
        if not FLIGHT_NUMBER.search(row["prompt"]):
            err("lookup_flight_number but no flight number in prompt")
    elif first == "airport_departures":
        if not first_leg.get("origin") or win is not True or real is False:
            err("airport_departures needs a known origin, in-window date and airline flight")
    elif first == "explain_limitation":
        if win is not False:
            err("explain_limitation is reserved for dates outside the AeroAPI window")
    if cat == "departure_window" and first != "airport_departures":
        err("departure_window cases must start with airport_departures")
    if cat == "flight_number" and first not in ("lookup_flight_number", "explain_limitation"):
        err("flight_number cases must start with a lookup or a window limitation")


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    errs: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"FAIL: cannot read {path}: {exc}")
        return 1

    rows = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            errs.append(f"line {n}: blank line")
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errs.append(f"line {n}: invalid JSON ({exc})")
            continue
        if not isinstance(obj, dict):
            errs.append(f"line {n}: not a JSON object")
            continue
        rows.append(obj)

    if len(rows) != EXPECTED_COUNT:
        errs.append(f"expected {EXPECTED_COUNT} rows, found {len(rows)}")
    for i, row in enumerate(rows, 1):
        want = f"IFD-{i:03d}"
        if row.get("id") != want:
            errs.append(f"row {i}: id {row.get('id')!r} != {want!r}")
        check_row(row, errs)

    ids = [r.get("id") for r in rows]
    for rid, k in Counter(ids).items():
        if k > 1:
            errs.append(f"duplicate id {rid}")

    cats = Counter(r.get("category") for r in rows)
    if sum(QUOTAS.values()) != EXPECTED_COUNT:
        errs.append("quota table does not sum to the expected count")
    for cat, quota in QUOTAS.items():
        if cats.get(cat, 0) != quota:
            errs.append(f"category {cat}: {cats.get(cat, 0)} != quota {quota}")

    prompts = [(r.get("id"), normalize(str(r.get("prompt", "")))) for r in rows]
    seen: dict[str, str] = {}
    for rid, p in prompts:
        if p in seen:
            errs.append(f"{rid}: duplicate prompt of {seen[p]}")
        seen.setdefault(p, rid)
    for i in range(len(prompts)):
        for j in range(i + 1, len(prompts)):
            ratio = difflib.SequenceMatcher(None, prompts[i][1], prompts[j][1]).ratio()
            if ratio >= NEAR_DUP_RATIO and prompts[i][1] != prompts[j][1]:
                errs.append(
                    f"{prompts[i][0]} ~ {prompts[j][0]}: near-duplicate prompts (ratio {ratio:.2f})"
                )

    exps = [r["expected"] for r in rows if isinstance(r.get("expected"), dict)]
    date_clarify = sum(1 for e in exps if "date" in (e.get("clarify_topics") or []))
    relative = sum(1 for r in rows if RELATIVE_DATE.search(str(r.get("prompt", ""))))
    aircraft = Counter(e.get("aircraft_icao") for e in exps)
    if date_clarify < MIN_DATE_CLARIFY:
        errs.append(
            f"only {date_clarify} cases require asking for the date (min {MIN_DATE_CLARIFY})"
        )
    if relative < MIN_RELATIVE_DATE:
        errs.append(f"only {relative} prompts use relative dates (min {MIN_RELATIVE_DATE})")
    for ac in sorted(SUPPORTED_AIRCRAFT):
        if aircraft.get(ac, 0) < 5:
            errs.append(f"supported aircraft {ac} appears {aircraft.get(ac, 0)} times (min 5)")
    unsupported = sum(k for a, k in aircraft.items() if a and a not in SUPPORTED_AIRCRAFT)
    if unsupported < 8:
        errs.append(f"only {unsupported} cases specify an unsupported aircraft (min 8)")

    print(f"File: {path}")
    print(f"Rows: {len(rows)}")
    print("Category counts:")
    for cat in QUOTAS:
        print(f"  {cat:24s} {cats.get(cat, 0):3d} / {QUOTAS[cat]}")
    print("First actions:", dict(Counter(e.get("first_action") for e in exps)))
    print("Aircraft:", {str(k): v for k, v in sorted(aircraft.items(), key=lambda kv: str(kv[0]))})
    print(f"Date must be asked: {date_clarify}; relative-date prompts: {relative}")
    print(
        "Real flight expected:",
        {str(k): v for k, v in Counter(e.get("real_flight_expected") for e in exps).items()},
    )
    print(
        "AeroAPI window:",
        {str(k): v for k, v in Counter(e.get("date_in_aeroapi_window") for e in exps).items()},
    )

    if errs:
        print(f"\nFAIL: {len(errs)} problem(s)")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
