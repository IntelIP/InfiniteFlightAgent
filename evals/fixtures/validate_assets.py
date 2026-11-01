"""Offline fixture integrity and synthetic request/normalization checks."""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from ifdispatcher import flights  # noqa: E402


def main():
    count = 0
    for path in (ROOT / "evals/fixtures").glob("*/*.json"):
        fixture = json.loads(path.read_text())
        assert fixture["schema_version"] == 1 and fixture["kind"] in (
            "synthetic",
            "derived_recording",
            "recorded",
        ), path
        datetime.fromisoformat(fixture["clock"])
        keys = set()
        for r in fixture["requests"]:
            key = json.dumps([r["path"], r["params"]], sort_keys=True)
            assert key not in keys, (path, key)
            keys.add(key)
            assert None not in r["params"].values()
            assert isinstance(r["status_code"], int) and isinstance(r["body"], dict)
        assert fixture["provenance"]["sources"]
        count += 1
    cases = [
        json.loads(s)
        for s in (ROOT / "evals/fixtures/synthetic_cases.jsonl").read_text().splitlines()
    ]
    for index, case in enumerate(cases, 1):
        fixture = json.loads((ROOT / case["fixture"]).read_text())

        class Frozen(datetime):
            @classmethod
            def now(_cls, tz=None):
                value = datetime.fromisoformat(fixture["clock"])
                return value.astimezone(tz) if tz else value.replace(tzinfo=None)

        flights.datetime = Frozen

        def get(path, params=None, transport=None):
            params = {k: v for k, v in (params or {}).items() if v is not None}
            matches = [
                r for r in fixture["requests"] if r["path"] == path and r["params"] == params
            ]
            assert len(matches) == 1, (case["id"], path, params)
            r = matches[0]
            if r["status_code"] >= 400:
                raise ValueError(f"http_error: AeroAPI returned {r['status_code']}")
            return r["body"]

        flights._get = get
        for code in ("KIAD", "KEWR"):
            assert flights.airport_name(code)
        if index == 12:
            try:
                flights.find_route_flights("KIAD", "KEWR", "2026-10-31", "UA")
            except ValueError as e:
                assert "503" in str(e)
            else:
                raise AssertionError("Expected synthetic HTTP 503")
            continue
        if index == 10:
            result = flights.get_flight_by_number("UA9111", "2026-10-31", "KIAD")
        elif index == 11:
            result = flights.find_airport_departures(
                "KIAD", "2026-10-31", "19:00", "21:00", destination="KEWR"
            )
        else:
            result = flights.find_route_flights(
                "KIAD",
                "KEWR",
                "2026-11-01" if index == 8 else "2026-10-31",
                "AV" if index == 4 else "UA",
            )
        rows = result["data"]
        assert len(rows) == (0 if index == 2 else 2 if index == 8 else 1), (case["id"], len(rows))
        assert all(f["fa_flight_id"].startswith("SYNTH-") for f in rows)
        if index == 3:
            assert rows[0]["departure_gate"] == rows[0]["aircraft_type"] == "unavailable"
            assert flights.recent_gates("UA9101", "KIAD")["status"] == "no_flights"
        if index == 4:
            assert rows[0]["codeshares"] == ["AV9911"]
        if index == 5:
            assert result["truncated"]
        if index == 6:
            assert (
                rows[0]["times"]["estimated_out"]["utc"] != rows[0]["times"]["scheduled_out"]["utc"]
            )
        if index == 7:
            assert rows[0]["cancelled"]
        if index == 8:
            assert [f["times"]["scheduled_out"]["local"] for f in rows] == [
                "2026-11-01 01:30 EDT",
                "2026-11-01 01:30 EST",
            ]
            query = next(r for r in fixture["requests"] if "/to/" in r["path"])["params"]
            assert (
                datetime.fromisoformat(query["end"].replace("Z", "+00:00"))
                - datetime.fromisoformat(query["start"].replace("Z", "+00:00"))
            ).total_seconds() == 25 * 3600
        if index == 9:
            assert rows[0]["times"]["scheduled_out"]["local"].startswith("2026-10-31 23:30")
        if index == 11:
            assert rows[0]["flight_number"] == "UA9112"
    print(f"Validated {count} fixture contracts and {len(cases)} synthetic scenarios offline")


if __name__ == "__main__":
    main()
