"""Reconstruct filtered snapshots, NOT raw HTTP replays. Standard library only."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "artifacts/evals"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def messages(row):
    for m in row.get("transcript", []):
        if m.get("role") == "tool":
            try:
                d = json.loads(m.get("text", ""))
            except (ValueError, TypeError):
                continue
            if isinstance(d, dict):
                yield m.get("name"), d


def timezone_from_times(f, arrival=False):
    for key, t in f.get("times", {}).items():
        if key.endswith("_in") != arrival or not t.get("utc") or not t.get("local"):
            continue
        utc = datetime.fromisoformat(t["utc"].replace("Z", "+00:00")).replace(tzinfo=None)
        local = datetime.strptime(t["local"][:16], "%Y-%m-%d %H:%M")
        hours = round((local - utc).total_seconds() / 3600, 2)
        # Minute formatting loses seconds; tolerate that, never invent fractional zones.
        if abs(hours - round(hours)) < 0.02:
            offset = round(hours)
            return "Etc/UTC" if offset == 0 else f"Etc/GMT{-offset:+d}"
    return None


def denormalize(f, airports):
    raw = {key: f.get(key) for key in ("ident_icao", "fa_flight_id", "status", "cancelled")}
    raw.update(
        ident_iata=f.get("flight_number"),
        ident=f.get("ident_icao") or f.get("flight_number"),
        operator=f.get("operator"),
        operator_iata=f.get("operator"),
        codeshares_iata=f.get("codeshares", []),
    )
    for side in ("origin", "destination"):
        a = f.get(side) or {}
        code = a.get("icao")
        raw[side] = {"code_icao": code, "code_iata": a.get("iata")}
        tz = timezone_from_times(f, side == "destination")
        if tz:
            raw[side]["timezone"] = tz
            airports.setdefault(code, {}).setdefault("timezone", tz)
    for key, t in f.get("times", {}).items():
        raw[key] = t.get("utc")
    for dest, src in {
        "gate_origin": "departure_gate",
        "terminal_origin": "departure_terminal",
        "gate_destination": "arrival_gate",
        "aircraft_type": "aircraft_type",
        "registration": "registration",
    }.items():
        raw[dest] = None if f.get(src) == "unavailable" else f.get(src)
    # actual_in/on were discarded by normalization: do not fabricate an arrival time.
    return raw


def build(row, source, digest, registry=None):
    tools = list(messages(row))
    clock = next((d["utc"] for n, d in tools if n == "current_time" and d.get("utc")), None)
    if not clock:
        clock = next((d["observed_at"] for n, d in tools if d.get("observed_at")), None)
    if not clock:
        return None, "no recorded clock"
    airports = {}
    for m in row.get("transcript", []):
        if m.get("role") == "approval":
            for code, name in re.findall(r"^(?:From|To)\s+(\w+): (.+)$", m.get("text", ""), re.M):
                airports.setdefault(code, {})["name"] = name
    for n, d in tools:
        if n == "check_airports":
            for code, name in d.items():
                if isinstance(name, str):
                    airports.setdefault(code, {})["name"] = name
    requests = {}
    limitations = set()
    for name, d in tools:
        if name not in {
            "find_route_flights",
            "find_airport_departures",
            "get_flight_by_number",
            "refresh_flight",
        }:
            continue
        if d.get("status") not in ("ok", "no_flights"):
            limitations.add(f"{name}: {d.get('status')} cannot reconstruct HTTP response")
            continue
        for ref in d.get("source_refs", []):
            match = re.search(r"GET (\S+)(?: (\S+)\.\.(\S+))?", ref)
            if not match:
                continue
            path, start, end = match.groups()
            if path.startswith("/airports/"):
                airports.setdefault(path.split("/")[2], {})
                if "/to/" in path:
                    airports.setdefault(path.rsplit("/", 1)[1], {})
            # Source envelopes carry seconds but current_time only carries minutes.
            # Rebase only clock-relative clipping/default-window boundaries.
            if d.get("observed_at"):
                observed = datetime.fromisoformat(d["observed_at"].replace("Z", "+00:00"))
                frozen = datetime.fromisoformat(clock.replace("Z", "+00:00"))
                values = [start, end]
                for i, value in enumerate(values):
                    if not value:
                        continue
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    for days in (-10, -1, 2):
                        if abs((parsed - observed - timedelta(days=days)).total_seconds()) < 120:
                            values[i] = (frozen + timedelta(days=days)).strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            )
                            limitations.add(
                                "Clock-relative request bounds rebased to first recorded clock; original source reference retained in provenance capture."
                            )
                            break
                start, end = values
            params = {}
            if start:
                params.update(
                    start=start, end=end, max_pages=3 if path.startswith("/airports/") else 2
                )
            if "/flights/to/" in path:
                params.update(type="Airline", connection="nonstop")
                key = "flights"
            elif path.startswith("/airports/"):
                # Airline query argument is absent from transcripts. Only the generic
                # request can be reconstructed; unrecognized airline queries fail closed.
                params["type"] = "Airline"
                key = path.rsplit("/", 1)[1]
                limitations.add(
                    "departure-board airline parameter unavailable; generic filtered subset only"
                )
            else:
                key = "flights"
                if start:
                    params["ident_type"] = "designator"
            rows = d.get("data") or []
            if isinstance(rows, dict):
                rows = [rows]
            raw = [
                denormalize(f, airports)
                for f in rows
                if isinstance(f, dict) and f.get("fa_flight_id")
            ]
            body = {
                key: [{"segments": [f]} for f in raw] if "/flights/to/" in path else raw,
                "num_pages": 1,
                "links": {"next": "unavailable-reconstructed-pagination"}
                if d.get("truncated")
                else None,
            }
            request = dict(path=path, params=params, status_code=200, body=body)
            # First response for each exact request is deterministic; do not union changing observations.
            requests.setdefault(json.dumps([path, params], sort_keys=True), request)
    if not requests:
        return None, "no reconstructable flight HTTP source references"
    sources = [dict(path=str(source), sha256=digest, case_id=row["id"])]
    for code, meta in airports.items():
        for field, (value, ref) in (registry or {}).get(code, {}).items():
            if not meta.get(field):
                meta[field] = value
                if ref not in sources:
                    sources.append(ref)
    missing = sorted(k for k, v in airports.items() if k and not v.get("name"))
    if missing:
        limitations.add("airport names unavailable: " + ", ".join(missing))
    meta = [
        dict(path=f"/airports/{k}", params={}, status_code=200, body=v)
        for k, v in sorted(airports.items())
        if k
    ]
    return dict(
        schema_version=1,
        kind="derived_recording",
        clock=datetime.fromisoformat(clock.replace("Z", "+00:00")).isoformat(),
        provenance=dict(
            generator="GPT-6-Astra",
            sources=sources,
            description="Reconstructed raw-shaped FILTERED SUBSET from normalized tool output; not a raw HTTP recording.",
            limitations=sorted(
                limitations
                | {
                    "Original tool arguments, pre-filter rows, page count, and actual arrival timestamps unavailable. num_pages=1 is a reconstruction placeholder, not measured usage.",
                    "Recent-gate summaries cannot reconstruct underlying flight occurrences and are omitted; unknown requests must fail closed.",
                    "Timezone is a fixed Etc/GMT offset inferred from recorded UTC/local pairs, not recovered IANA airport timezone; DST transitions are not reconstructed.",
                    "Only first observed response per exact request retained; normalized historical classification may not round-trip without discarded arrival timestamps.",
                }
            ),
        ),
        requests=meta + list(requests.values()),
    ), None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    cases = [
        json.loads(s)
        for s in (ROOT / "evals/dispatch_prompts.jsonl").read_text().splitlines()
        if s.strip()
    ]
    candidates = {}
    registry = {}
    for path in sorted(
        args.source_root.glob("*/results.jsonl"),
        key=lambda p: re.search(r"\d{8}T\d{6}Z", p.parent.name).group(0)
        if re.search(r"\d{8}T\d{6}Z", p.parent.name)
        else p.parent.name,
        reverse=True,
    ):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            candidates.setdefault(row.get("id"), []).append((row, path, digest))
            ref = dict(path=str(path), sha256=digest, case_id=row.get("id"))
            for m in row.get("transcript", []):
                if m.get("role") == "approval":
                    for code, name in re.findall(
                        r"^(?:From|To)\s+(\w+): (.+)$", m.get("text", ""), re.M
                    ):
                        registry.setdefault(code, {}).setdefault("name", (name, ref))
            for n, d in messages(row):
                if n == "check_airports":
                    for code, name in d.items():
                        if isinstance(name, str):
                            registry.setdefault(code, {}).setdefault("name", (name, ref))
                rows = d.get("data") or []
                if isinstance(rows, dict):
                    rows = [rows]
                if not isinstance(rows, list):
                    continue
                for f in rows:
                    if not isinstance(f, dict) or not f.get("fa_flight_id"):
                        continue
                    for side in ("origin", "destination"):
                        code = (f.get(side) or {}).get("icao")
                        tz = timezone_from_times(f, side == "destination")
                        if code and tz:
                            registry.setdefault(code, {}).setdefault("timezone", (tz, ref))
    report = {
        "covered": [],
        "uncovered": [],
        "meaning": "Covered means some reconstructable requests, NOT full conversation replay coverage.",
    }
    for case in cases:
        reasons = []
        for row, path, digest in candidates.get(case["id"], []):
            result, reason = build(row, path, digest, registry)
            if result:
                write(ROOT / f"evals/fixtures/recorded/{case['id']}.json", result)
                missing_metadata = {
                    r["path"]: [k for k in ("name", "timezone") if not r["body"].get(k)]
                    for r in result["requests"]
                    if r["path"].startswith("/airports/") and r["path"].count("/") == 2
                }
                missing_metadata = {k: v for k, v in missing_metadata.items() if v}
                report["covered"].append(
                    {
                        "id": case["id"],
                        "source": str(path),
                        "requests": len(result["requests"]),
                        "missing_airport_metadata": missing_metadata,
                    }
                )
                break
            reasons.append(reason)
        else:
            report["uncovered"].append(
                {"id": case["id"], "reasons": sorted(set(reasons)) or ["no historical transcript"]}
            )
    report["covered_count"] = len(report["covered"])
    report["uncovered_count"] = len(report["uncovered"])
    report["cases_with_missing_airport_metadata"] = sum(
        bool(c["missing_airport_metadata"]) for c in report["covered"]
    )
    write(ROOT / "evals/fixtures/recording_coverage.json", report)
    print(json.dumps({k: report[k] for k in ("covered_count", "uncovered_count")}))


if __name__ == "__main__":
    main()
