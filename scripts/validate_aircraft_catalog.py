"""Validate the frozen research inventory without network or simulator/provider calls."""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "docs/research/evidence/aircraft-catalog-v26.json"


def validate(catalog: dict) -> dict:
    """Reject incomplete inventories and research promoted into unsupported verification."""
    rows = catalog["records"]
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate aircraft id")
    current = [r for r in rows if not r["legacy"]]
    counts = catalog["denominator"]
    expected = {
        "source_records": len(rows),
        "current_fleet": len(current),
        "legacy_excluded": len(rows) - len(current),
        "strict_majority": len(current) // 2 + 1,
        "verified_supported": sum(r["support_verified"] for r in current),
        "implemented_estimate_entries": sum(
            r["profile_status"] == "implemented_estimate_unverified" for r in current
        ),
    }
    if any(counts.get(key) != value for key, value in expected.items()):
        raise ValueError("denominator/count mismatch")
    if counts["eligible_subset"] is not None:
        raise ValueError("this snapshot must preserve the raw current-fleet denominator")
    sources = {s["id"] for s in catalog["sources"]}
    if len(sources) != len(catalog["sources"]):
        raise ValueError("duplicate source id")
    for source in catalog["sources"]:
        datetime.fromisoformat(source["retrieved_at_utc"])
        if not re.fullmatch(r"[a-f0-9]{64}", source["response_sha256"]):
            raise ValueError("missing response identity")
        if not source["url"].startswith("https://") or not source["license"]:
            raise ValueError("missing source/access rights")
    changes = {c["id"]: c for c in catalog["changes"]}
    if len(changes) != len(catalog["changes"]):
        raise ValueError("duplicate change id")
    for change in changes.values():
        if change["source"] not in sources or change["kind"] not in {"app", "ota", "documentation"}:
            raise ValueError("invalid change evidence")
        if change["kind"] == "app" and not (change.get("version") and change.get("build")):
            raise ValueError("app changes need a version and build")
        if change["kind"] == "ota" and "build" in change:
            raise ValueError("OTA content must not masquerade as an app build")
    gaps = set(catalog["shared_gaps"])
    for row in rows:
        if not (row["name"] and row["icao_from_fleet"] and row["listed_powerplants"]):
            raise ValueError("incomplete airframe/engine identity")
        refs = [row["fleet_source"], row["simbrief"]["source"], *row["native"]["source_refs"]]
        if not set(refs) <= sources or not set(row["change_refs"]) <= set(changes):
            raise ValueError("dangling evidence reference")
        if not set(row["unresolved"]) <= gaps:
            raise ValueError("unknown gap reference")
        if row["simbrief"]["id"] is None and row["simbrief"]["tlr_data"] is not None:
            raise ValueError("unmapped profile cannot claim runway data")
        if row["displayed_target_type"] and not row["native"]["simulator_observed"]:
            raise ValueError("unobserved displayed target")
        if row["support_verified"] and not row.get("acceptance_evidence"):
            raise ValueError("verified support requires aircraft acceptance evidence")
        if row["legacy"] and row["change_refs"]:
            raise ValueError("current-fleet changes inferred for a legacy record")
    return expected


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else CATALOG
    try:
        result = validate(json.loads(path.read_text()))
    except (KeyError, TypeError, ValueError) as exc:
        sys.exit(f"invalid catalog: {exc}")
    print(json.dumps({"status": "passed", **result}, sort_keys=True))
