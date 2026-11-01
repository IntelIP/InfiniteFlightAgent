"""Record BUILD-04 live acceptance from the deployed service's own records.

    doppler run -p <project> -c <config> --only-secrets DATABASE_URL -- \\
      uv run python scripts/record_live_acceptance.py --commit <deployed sha> \\
      --version <Worker version id> --case <thread_id>=<trip> [--case ...]

Reads the production database without writing to it: checkpoint writes show the approval wait
and resume, leg_meta the browser generation, snapshots the retained OFPs. Run it from a checkout
whose integration code matches the deployed commit. Writes docs/evidence/live-acceptance.json;
exits non-zero while any outcome is unshown.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import psycopg

import acceptance


def legs(db, trip: str) -> list[dict]:
    rows = db.execute(
        "SELECT m.leg, m.revision, m.payload, r.payload, s.normalized, s.sha256, s.retrieved_at "
        "FROM leg_meta m JOIN requests r USING (trip, leg, revision) "
        "LEFT JOIN snapshots s USING (trip, leg, revision) "
        "WHERE m.trip = %s ORDER BY m.leg, m.revision",
        (trip,),
    ).fetchall()
    found = []
    for leg, revision, meta, request, normalized, sha, retrieved_at in rows:
        meta, request = json.loads(meta), json.loads(request)
        generation = meta.get("generation") or {}
        plan = json.loads(normalized) if normalized else None
        found.append(
            {
                "leg": leg,
                "revision": revision,
                "requested": {
                    k: request[k] for k in ("origin", "destination", "aircraft", "departure")
                },
                "generation": {
                    "status": generation.get("status"),
                    "clicked_at": generation.get("at"),
                    "browser_session": bool(generation.get("session")),
                },
                "snapshot": plan
                and {
                    "sha256": sha,
                    "retrieved_at": retrieved_at,
                    "generated_at": plan.get("generated_at"),
                    "origin": plan.get("origin"),
                    "destination": plan.get("destination"),
                    "aircraft": (plan.get("aircraft") or {}).get("icao_code"),
                    "takeoff_status": plan.get("takeoff_status"),
                },
            }
        )
    return found


def writes(db, thread: str, channel: str) -> int:
    return db.execute(
        "SELECT count(*) FROM checkpoint_writes WHERE thread_id = %s AND channel = %s",
        (thread, channel),
    ).fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", required=True, help="full SHA of the deployed commit")
    parser.add_argument("--version", required=True, help="Worker version id that served the run")
    parser.add_argument("--case", action="append", required=True, help="thread_id=trip")
    args = parser.parse_args()

    changed = subprocess.run(
        ["git", "diff", "--quiet", args.commit, "--", *acceptance.INTEGRATION],
        cwd=acceptance.ROOT,
    ).returncode
    if changed:
        sys.exit(f"Integration code in this checkout differs from {args.commit[:7]}.")

    cases = []
    with psycopg.connect(os.environ["DATABASE_URL"], prepare_threshold=None) as db:
        for case in args.case:
            thread, _, trip = case.partition("=")
            cases.append(
                {
                    "thread": thread,
                    "trip": trip,
                    "interrupts": writes(db, thread, "__interrupt__"),
                    "resumes": writes(db, thread, "__resume__"),
                    "legs": legs(db, trip),
                }
            )
    shown = acceptance.outcomes(cases)
    evidence = {
        "schemaVersion": "ifd-live-acceptance/v1",
        "acceptance": "BUILD-04",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "deployment": {"commit": args.commit, "worker_version": args.version},
        "integration_digest": acceptance.integration_digest(),
        "outcomes": shown,
        "cases": cases,
    }
    acceptance.EVIDENCE.write_text(json.dumps(evidence, indent=2) + "\n")
    for name, outcome in shown.items():
        print(f"{'PASS' if outcome['passed'] else 'MISS'} {name}: {outcome['detail']}")
    sys.exit(0 if all(outcome["passed"] for outcome in shown.values()) else 1)


if __name__ == "__main__":
    main()
