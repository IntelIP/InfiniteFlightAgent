"""Outcome equivalence never excuses changed profiles, invented times or approval bypass."""

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
from run_workflow_replay import run_case  # noqa: E402
from workflow_evaluations import load_manifest, verify  # noqa: E402


@pytest.fixture(scope="module")
def standard_run():
    manifest = load_manifest(ROOT / "evals/workflow_cases_v044.json")
    case = next(c for c in manifest["cases"] if c["id"] == "WF-010")
    return case, run_case(case, manifest)


def omitted_standard_profile(run):
    row = copy.deepcopy(run)
    row["state"][0]["request"]["airframe_id"] = None
    row["state"][0]["raw"]["aircraft"]["internal_id"] = "A20N"
    for approval in row["approvals"]:
        for name in ("args", "resolved_args"):
            if name in approval:
                approval[name]["airframe_id"] = None
    return row


def test_builtin_profile_omission_preserves_exact_aircraft_and_approval(standard_run):
    case, original = standard_run
    row = omitted_standard_profile(original)
    checks = verify(case, row)["checks"]
    assert checks["intent_input_identity"]
    assert checks["approval_bounds"]
    assert checks["correlated_immutable_ofps"]
    for field, wrong in (("aircraft", "B38M"), ("passengers", 99), ("route", "OTHER ROUTE")):
        changed = copy.deepcopy(row)
        changed["state"][0]["request"][field] = wrong
        # Route is not a settled input in WF010, so explicitly establish it for this check.
        changed_case = copy.deepcopy(case)
        if field == "route":
            changed_case["legs"][0]["route"] = "JCOBY4 SWANN PHLBO4"
        assert not verify(changed_case, changed)["checks"]["intent_input_identity"]


@pytest.mark.parametrize("custom", ["CL35", "123_456"])
def test_omission_never_substitutes_a_custom_or_different_standard_profile(standard_run, custom):
    case, original = standard_run
    case = copy.deepcopy(case)
    case["legs"][0]["airframe_id"] = custom
    row = omitted_standard_profile(original)
    checks = verify(case, row)["checks"]
    assert not checks["intent_input_identity"]
    assert not checks["approval_bounds"]
    row["state"][0]["request"]["airframe_id"] = custom
    assert not verify(case, row)["checks"]["correlated_immutable_ofps"]


def test_unknown_connection_can_be_established_from_saved_state_without_a_tool_order():
    manifest = load_manifest(ROOT / "evals/workflow_cases_v044.json")
    case = copy.deepcopy(next(c for c in manifest["cases"] if c["id"] == "WF-027"))
    case.pop("tool_assertions", None)
    case.update(unknown_connection=True, settled_approval=True)
    case["script"] = [
        case["script"][0],
        {"tool": "saved_trips", "args": {"trip": case["legs"][0]["trip"]}},
        {
            "text": "The approved first leg is prepared, with no plan generated. The connection is unverified because arrival is unknown."
        },
    ]
    row = run_case(case, manifest)
    assert row["passed"], row["constraint_failures"]
    assert not any(t["name"] == "check_connection" for t in row["tool_results"])
    assert row["clicks"] == []

    changed = copy.deepcopy(row)
    changed["final_reply"] += " Leg 1 arrives at 14:00 UTC."
    assert not verify(case, changed)["checks"]["missing_arrival_explicit"]
    changed = copy.deepcopy(row)
    changed["final_reply"] += " Awaiting your approval."
    assert not verify(case, changed)["checks"]["settled_approval_not_reasked"]
    changed = copy.deepcopy(row)
    changed["observations"][-1]["approved"] = []
    assert not verify(case, changed)["checks"]["approval_bounds"]
    changed = copy.deepcopy(row)
    changed["state"][0]["meta"]["planned_arrival"] = "2026-11-08T14:00:00Z"
    assert not verify(case, changed)["checks"]["missing_arrival_explicit"]


@pytest.mark.parametrize("status", ["no_previous_leg", "arrival_unavailable"])
def test_explicit_unknown_connection_status_never_licenses_an_arrival(status):
    manifest = load_manifest(ROOT / "evals/workflow_cases_v044.json")
    case = copy.deepcopy(next(c for c in manifest["cases"] if c["id"] == "WF-027"))
    case.pop("tool_assertions", None)
    case.update(unknown_connection=True, settled_approval=True)
    row = run_case(case, manifest)
    row["tool_results"] = [t for t in row["tool_results"] if t["name"] != "saved_trips"]
    result = {"name": "check_connection", "output": {"status": status}, "status": "success"}
    row["tool_results"] = [t for t in row["tool_results"] if t["name"] != "check_connection"] + [
        result
    ]
    assert verify(case, row)["checks"]["missing_arrival_explicit"]
    result["output"]["arrival_utc"] = "2026-11-08T14:00:00Z"
    assert not verify(case, row)["checks"]["missing_arrival_explicit"]
