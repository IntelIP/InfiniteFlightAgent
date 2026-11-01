"""Live acceptance for BUILD-04 (docs/implementation/simbrief-build-spec.md).

Local tests cannot close BUILD-04. scripts/record_live_acceptance.py derives each outcome from
the deployed service's own records and writes EVIDENCE; scripts/validate.py passes only while
that evidence shows every outcome and the integration code still matches what was live.
"""

import hashlib
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/live-acceptance.json"
# Code whose change invalidates a live run: the service, its Worker, its image and dependencies.
INTEGRATION = (
    "src/ifdispatcher",
    "deploy/cloudflare/src",
    "deploy/cloudflare/wrangler.toml",
    "Dockerfile",
    "uv.lock",
)
OUTCOMES = {
    "generation_through_mcp": "A plan generated through the deployed MCP service, OFP retained",
    "neo_response": "A real neo OFP with takeoff performance",
    "two_legs_retained": "Two legs of one trip kept after the latest SimBrief plan changed",
    "authentication_and_resumption": "Signed-in generation after an approval wait and resume",
}
NEO = {"A20N", "A21N", "B38M"}


def integration_digest() -> str:
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", *INTEGRATION],
        cwd=ROOT,
        text=True,
    ).split()
    digest = hashlib.sha256()
    for name in sorted(names):
        path = ROOT / name
        if path.is_file():
            digest.update(f"{name}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n".encode())
    return digest.hexdigest()


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def correlated(leg: dict) -> bool:
    """Browser-generated, and the retained OFP matches the request and postdates the click."""
    generation, plan, asked = leg["generation"], leg["snapshot"], leg["requested"]
    return bool(
        generation["status"] == "generated"
        and generation["browser_session"]
        and generation["clicked_at"]
        and plan
        and plan["generated_at"]
        and (plan["origin"], plan["destination"], plan["aircraft"])
        == (asked["origin"], asked["destination"], asked["aircraft"])
        and _time(plan["generated_at"]) >= _time(generation["clicked_at"]) - timedelta(minutes=1)
    )


def outcomes(cases: list[dict]) -> dict[str, dict]:
    """Decide each outcome from recorded cases: {thread, trip, interrupts, resumes, legs}."""
    good = [(case, leg) for case in cases for leg in case["legs"] if correlated(leg)]

    def result(passed: bool, detail: str) -> dict:
        return {"passed": passed, "detail": detail}

    neo = [
        f"{case['trip']} leg {leg['leg']} ({leg['snapshot']['aircraft']})"
        for case, leg in good
        if leg["snapshot"]["aircraft"] in NEO and leg["snapshot"]["takeoff_status"] == "available"
    ]
    two = []
    for case in cases:
        legs = sorted(
            (leg for leg in case["legs"] if correlated(leg)),
            key=lambda leg: leg["generation"]["clicked_at"],
        )
        for first, later in zip(legs, legs[1:]):
            if (
                first["leg"] != later["leg"]
                and first["snapshot"]["sha256"] != later["snapshot"]["sha256"]
                and _time(first["snapshot"]["retrieved_at"])
                < _time(later["generation"]["clicked_at"])
            ):
                two.append(f"{case['trip']} legs {first['leg']} and {later['leg']}")
    resumed = [
        case["trip"]
        for case in cases
        if case["interrupts"] and case["resumes"] and any(correlated(leg) for leg in case["legs"])
    ]
    return {
        "generation_through_mcp": result(
            bool(good),
            ", ".join(f"{case['trip']} leg {leg['leg']}" for case, leg in good)
            or "no correlated browser generation",
        ),
        "neo_response": result(bool(neo), ", ".join(neo) or "no neo OFP with takeoff data"),
        "two_legs_retained": result(
            bool(two), ", ".join(two) or "no trip with two retained, generated legs"
        ),
        "authentication_and_resumption": result(
            bool(resumed),
            ("approval wait, resume and signed-in generation: " + ", ".join(resumed))
            if resumed
            else "no generated trip with an approval wait and resume",
        ),
    }


def gap() -> str | None:
    """Why live acceptance is not established for this code, or None when it is."""
    if not EVIDENCE.exists():
        return (
            "No live acceptance evidence; run scripts/record_live_acceptance.py after a live run."
        )
    evidence = json.loads(EVIDENCE.read_text())
    shown = evidence.get("outcomes", {})
    missing = [name for name in OUTCOMES if not shown.get(name, {}).get("passed")]
    if missing:
        return "Live acceptance incomplete: " + ", ".join(missing) + " not shown."
    if evidence.get("integration_digest") != integration_digest():
        commit = evidence.get("deployment", {}).get("commit", "")[:7]
        return f"Integration code changed since live acceptance on {commit}; repeat it."
    return None
