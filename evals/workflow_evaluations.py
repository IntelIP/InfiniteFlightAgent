"""Versioned whole-workflow oracles and matched comparisons. No network on import."""

import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evals/workflow_cases.json"
VERIFIER_VERSION = "ifd-workflow-oracles-v3"
EVIDENCE_MODES = {
    "scripted-controlled",
    "real-model-replay",
    "live-provider",
    "reference",
    "simulator",
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def load_manifest(path=MANIFEST) -> dict:
    manifest = json.loads(Path(path).read_text())
    if manifest.get("schema_version") != 1 or manifest.get("verifier_version") not in {
        "ifd-workflow-oracles-v1",
        "ifd-workflow-oracles-v2",
        VERIFIER_VERSION,
    }:
        raise ValueError("unsupported workflow manifest/verifier version")
    ids = [case["id"] for case in manifest["cases"]]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("case IDs must be nonempty and unique")
    if datetime.fromisoformat(manifest["clock_utc"].replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("fixture clock requires timezone")
    fixture = manifest["fixture"]
    if sha256((ROOT / fixture["path"]).read_bytes()) != fixture["sha256"]:
        raise ValueError("fixture digest differs from frozen manifest")
    if sha256((ROOT / fixture["provenance_path"]).read_bytes()) != fixture["provenance_sha256"]:
        raise ValueError("fixture provenance differs from frozen manifest")
    return manifest


def source_identity() -> dict:
    """Digest the actual worktree, including untracked Python/evaluation inputs, without secrets."""
    paths = sorted(
        p
        for folder in ("src", "evals")
        for p in (ROOT / folder).rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".json", ".jsonl"}
        and "__pycache__" not in p.parts
        and "recorded" not in p.parts
    ) + [
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        ROOT / "instructions.md",
        ROOT / "scripts/review_traces.py",
        ROOT / "tests/test_workflow_evaluations.py",
        ROOT / "tests/test_remote.py",
    ]
    files = {str(p.relative_to(ROOT)): sha256(p.read_bytes()) for p in paths if p.exists()}

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    status = git("status", "--porcelain", "--untracked-files=normal")
    return {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(status),
        "source_sha256": sha256(canonical(files)),
        "source_files": files,
        "langsmith_version": version("langsmith"),
    }


def key(args: dict) -> tuple:
    return args["trip"], args["leg"], args.get("revision", 1)


def expected_request(args: dict) -> dict:
    return {
        (
            "aircraft"
            if field == "sim_aircraft"
            else "departure"
            if field == "departure_utc"
            else field
        ): value
        for field, value in args.items()
        if field not in {"departure_local_date", "private_callsign", "engine", "fa_flight_id"}
    }


def same_value(field, left, right):
    if field in {"departure", "departure_utc"}:
        try:
            return datetime.fromisoformat(left.replace("Z", "+00:00")) == datetime.fromisoformat(
                right.replace("Z", "+00:00")
            )
        except (AttributeError, TypeError, ValueError):
            return False
    return left == right


def same_input(field, left, right, aircraft):
    # Selecting basetype waits for #type == aircraft before an optional airframe override.
    # Omission and that same built-in type select the same profile; custom IDs do not.
    if (
        field == "airframe_id"
        and isinstance(aircraft, str)
        and re.fullmatch(r"[A-Z0-9]{2,4}", aircraft)
        and left in (None, aircraft)
        and right in (None, aircraft)
    ):
        return True
    return same_value(field, left, right)


def verify(case: dict, run: dict) -> dict:
    """Check observed end state, not a prescribed model tool sequence or a blended score."""
    state = run.get("state", [])
    expected = {} if case.get("no_dispatch") else {key(leg): leg for leg in case["legs"]}
    declined = case["scenario"] == "decline"
    blocked = case["expected_outcome"] == "blocked"
    actual = {key(row["request"]): row for row in state}
    checks = {}
    checks["intent_input_identity"] = not actual if declined else set(actual) == set(expected)
    for ident, row in actual.items():
        want = expected.get(ident)
        if not want:
            checks["intent_input_identity"] = False
            continue
        checks["intent_input_identity"] &= all(
            same_input(field, row["request"].get(field), value, want["sim_aircraft"])
            for field, value in expected_request(want).items()
        ) and row["meta"].get("private_callsign") == want.get("private_callsign")

    approvals = run.get("approvals", [])
    approved = [a.get("resolved_args", a["args"]) for a in approvals if a["decision"] == "approve"]
    checks["approval_bounds"] = (
        not approvals if case.get("no_dispatch") else bool(approvals)
    ) and all(
        a["name"] in {"dispatch_flight", "revise_dispatch"}
        and key(a.get("resolved_args", a["args"])) in expected
        and all(
            same_input(
                f,
                a.get("resolved_args", a["args"]).get(
                    f, 1 if f == "revision" else "KGS" if f == "units" else None
                ),
                v,
                expected[key(a.get("resolved_args", a["args"]))]["sim_aircraft"],
            )
            for f, v in expected[key(a.get("resolved_args", a["args"]))].items()
        )
        for a in approvals
    )
    # Each observation was taken before granting the next approval. A request/click must
    # already have an exact approved identity, including when the model bypasses dispatch.
    checks["approval_bounds"] &= all(
        all(
            tuple(ident) in {key(a) for a in observation["approved"]}
            for ident in observation["request_keys"] + observation["click_keys"]
        )
        for observation in run.get("observations", [])
    ) and (not approved if declined else {key(a) for a in approved} == set(expected))

    clicks = Counter(tuple(c["key"]) for c in run.get("clicks", []))
    checks["duplicate_generate_prevented"] = all(n <= 1 for n in clicks.values())
    checks["generation_bounds"] = sum(clicks.values()) == case.get(
        "expected_clicks", 0 if declined or blocked else len(expected)
    ) and set(clicks) <= set(expected)
    snapshots = [row for row in state if row.get("snapshot")]
    checks["retained_legs"] = len(snapshots) == case.get(
        "expected_snapshots", 0 if declined or blocked else len(expected)
    )
    provider_plans = run.get("provider_plans", [])
    checks["correlated_immutable_ofps"] = True
    for row in snapshots:
        raw, snapshot, request = row["raw"], row["snapshot"], row["request"]
        plan_matches = [p for p in provider_plans if p["sha256"] == snapshot["raw_sha256"]]
        generation = row["meta"].get("generation") or {}
        try:
            generated_at = datetime.fromisoformat(
                snapshot["data"]["generated_at"].replace("Z", "+00:00")
            )
            claimed_at = datetime.fromisoformat(generation["at"].replace("Z", "+00:00"))
            fresh_for_claim = (
                generated_at.tzinfo is not None
                and claimed_at.tzinfo is not None
                and generated_at >= claimed_at - timedelta(minutes=1)
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            fresh_for_claim = False
        checks["correlated_immutable_ofps"] &= (
            row["computed_sha256"] == snapshot["raw_sha256"]
            and bool(plan_matches)
            and fresh_for_claim
            and generation.get("clicked") is True
            and same_value(
                "departure", raw["params"]["time_generated"], snapshot["data"]["generated_at"]
            )
            and raw["origin"]["icao_code"] == request["origin"]
            and raw["destination"]["icao_code"] == request["destination"]
            and raw["aircraft"]["icao_code"] == request["aircraft"]
            and same_input(
                "airframe_id",
                raw["aircraft"]["internal_id"],
                request.get("airframe_id"),
                request["aircraft"],
            )
            and raw["params"]["units"].upper() == request["units"]
            and same_value("departure", raw["times"]["sched_out"], request["departure"])
            and int(raw["weights"]["pax_count"]) == request["passengers"]
            and (
                f"{raw['general'].get('icao_airline') or ''}{raw['general'].get('flight_number') or ''}"
                == row["meta"]["flight"]["ident_icao"]
                if row["meta"].get("flight")
                else raw["general"]["flight_number"] == row["meta"]["private_callsign"]
            )
        )
    history = {}
    for observation in run.get("observations", []):
        for ident, digest in observation["snapshot_hashes"]:
            ident = tuple(ident)
            checks["correlated_immutable_ofps"] &= ident not in history or history[ident] == digest
            history[ident] = digest
    checks["completion"] = run.get("workflow", {}).get("outcome") == case["expected_outcome"]
    if case["scenario"] == "revision_recovery":
        # A recovered refusal is a blocked latest tool step while the saved plan stays usable.
        checks["completion"] = bool(snapshots) and bool(run.get("final_reply"))
    if declined:
        checks["completion"] = not actual and not clicks and bool(run.get("final_reply"))
    elif blocked or case.get("no_dispatch"):
        checks["completion"] = bool(run.get("final_reply")) and not snapshots
    else:
        checks["completion"] &= all(
            row["meta"].get("briefing", "").startswith("**SPAWN:**") for row in snapshots
        )
    checks["infeasible_handling"] = None
    checks["unsupported_handling"] = None
    checks["revision_failure_recovery"] = None
    checks["provider_failure_contract"] = None
    checks["calibration_preserves_ofp"] = None
    if case["scenario"] == "retry_duplicate":
        finals = [
            t["output"] for t in run.get("tool_results", []) if t["name"] == "finalize_dispatch"
        ]
        checks["calibration_preserves_ofp"] = (
            bool(finals)
            and (
                finals[-1].get("thrust", {}).get("data", {}).get("calibration_full_thrust_n1") == 92
            )
            and len(run.get("provider_plans", [])) == 1
        )
    if case["scenario"] == "infeasible":
        checks["infeasible_handling"] = (
            bool(snapshots)
            and all(
                row["meta"].get("task_outcome") == "infeasible"
                and "withheld" in row["meta"].get("briefing", "")
                for row in snapshots
            )
            and "infeasible" in run.get("final_reply", "").lower()
        )
    if case["scenario"] == "unsupported":
        checks["unsupported_handling"] = (
            bool(snapshots)
            and all(
                "THRUST (simulation-grade estimate):** unavailable"
                in row["meta"].get("briefing", "")
                for row in snapshots
            )
            and "unavailable" in run.get("final_reply", "").lower()
        )
    if case["scenario"] == "revision_recovery":
        refused = [t for t in run.get("tool_results", []) if t["name"] == "revise_dispatch"]
        checks["revision_failure_recovery"] = (
            bool(refused)
            and all("unsupported" in json.dumps(t["output"]).lower() for t in refused)
            and len(actual) == 1
            and not run.get("error")
            and bool(run.get("final_reply"))
        )
    if case["scenario"] == "provider_failure" and case.get("provider_failure", "quota") in {
        "quota",
        "auth",
        "concurrency",
        "transient",
    }:
        failures = [
            t["output"] for t in run.get("tool_results", []) if t["name"] == "generate_in_simbrief"
        ]
        checks["provider_failure_contract"] = (
            bool(failures)
            and all(
                result.get("reason_code") == case.get("reason_code", "provider_quota_exhausted")
                and result.get("automatic_retry_allowed") is False
                and result.get("clicked") is False
                and bool(result.get("next"))
                for result in failures
            )
            and len(run.get("provider_attempts", [])) == 1
        )
    if case.get("route_evidence") and snapshots:
        checks["retained_route_evidence"] = all(
            row["snapshot"]["data"].get("flight_route")
            == case.get("retained_route", case["legs"][0].get("route") or "JCOBY4 SWANN PHLBO4")
            and [f["ident"] for f in row["raw"].get("navlog", {}).get("fix", [])]
            == case["route_evidence"]
            for row in snapshots
        )
    for assertion in case.get("tool_assertions", []):
        outputs = [
            t["output"] for t in run.get("tool_results", []) if t["name"] == assertion["tool"]
        ]

        def matches(output):
            for part in assertion["path"]:
                if not isinstance(output, dict) or part not in output:
                    return False
                output = output[part]
            return output == assertion["equals"]

        checks[assertion["id"]] = any(matches(o) for o in outputs)
    if case.get("unknown_connection"):
        unknown_results = [
            t["output"]
            for t in run.get("tool_results", [])
            if t["name"] == "check_connection"
            and t["output"].get("status") in {"no_previous_leg", "arrival_unavailable"}
            and not t["output"].get("follows")
            and not t["output"].get("arrival_utc")
        ]
        inspections = [
            t["output"]
            for t in run.get("tool_results", [])
            if t["name"] == "saved_trips" and t["output"].get("status") == "ok"
        ]
        reply = run.get("final_reply", "").lower()
        # This is a narrow language guard, not a semantic judge: pair it with observed
        # unknown state, no generation, and no asserted numeric arrival in this case.
        qualified = (
            "arriv" in reply
            and "connect" in reply
            and bool(
                re.search(
                    r"cannot|can't|can’t|unverified|unknown|unavailable|not (?:yet )?(?:known|verified)",
                    reply,
                )
            )
        )
        asserted_arrival = re.search(
            r"\b(?:arriv(?:e[sd]?|al(?: time)?)|lands?)\s*(?:is|:)?\s*(?:at|by)?\s*\d{1,2}:\d{2}",
            reply,
        )
        unknown_state = bool(state) and all(
            not row.get("snapshot")
            and not row["meta"].get("planned_arrival")
            and not row["meta"].get("flight")
            for row in state
        )
        inspected_preparation = any(
            any(
                saved.get("request") == row["request"]
                and saved.get("status") == "prepared"
                and not saved.get("snapshot_sha256")
                for saved in inspection.get("legs", [])
            )
            for inspection in inspections
            for row in state
        )
        checks["missing_arrival_explicit"] = (
            unknown_state
            and bool(unknown_results or inspected_preparation)
            and qualified
            and not asserted_arrival
            and not clicks
        )
    if case.get("settled_approval"):
        checks["settled_approval_not_reasked"] = bool(approved) and not re.search(
            r"\bawaiting (?:your |the )?(?:approval|confirmation)\b|"
            r"\bwaiting for (?:your )?(?:approval|confirmation)\b|"
            r"\bplease (?:approve|confirm)\b|\b(?:need|require)s? (?:your )?(?:approval|confirmation)\b",
            run.get("final_reply", "").lower(),
        )
    if run.get("mcp_saved") is not None:
        saved = run["mcp_saved"].get("legs", [])
        latest = {}
        for row in state:
            ident = key(row["request"])[:2]
            if (
                ident not in latest
                or row["request"]["revision"] > latest[ident]["request"]["revision"]
            ):
                latest[ident] = row
        returned = {key(row["request"])[:2]: row for row in saved}
        checks["mcp_retained_results"] = (
            len(returned) == len(saved)
            and set(returned) == set(latest)
            and all(
                returned[ident]["request"] == row["request"]
                and returned[ident].get("snapshot_sha256")
                == (row["snapshot"]["raw_sha256"] if row["snapshot"] else None)
                and returned[ident].get("briefing_markdown") == row["meta"].get("briefing")
                for ident, row in latest.items()
            )
        )
    if case.get("claim_expected_status"):
        checks["uncertain_claim_preserved"] = (
            all(
                row["meta"].get("generation", {}).get("status") == case["claim_expected_status"]
                and row["meta"]["generation"].get("clicked") is True
                and row["meta"]["generation"].get("automatic_retry_allowed") is False
                for row in state
            )
            and len(run.get("provider_attempts", [])) == 1
        )
    if case.get("restart"):
        checks["restart_recovery"] = run.get("recovered", {}).get("status") == "saved" and run.get(
            "recovered", {}
        ).get("reply") == run.get("final_reply")
    checks["clarification_bounds"] = run.get("metrics", {}).get(
        "clarification_turns", 0
    ) <= case.get("max_clarifications", 5)
    checks["no_runtime_error"] = run.get("error") is None
    checks["no_tool_schema_errors"] = not run.get("metrics", {}).get("tool_schema_errors")
    failed = [name for name, passed in checks.items() if passed is False]
    return {"checks": checks, "constraint_failures": failed, "passed": not failed}


def compare(baseline: dict, candidate: dict) -> dict:
    """Only matched, valid cases are compared; absent/invalid runs remain visible."""
    compatibility = [
        name
        for name in (
            "suite_sha256",
            "verifier_version",
            "harness_sha256",
            "evidence_mode",
            "model",
            "effort",
        )
        if baseline.get(name) != candidate.get(name)
    ]
    for label, batch in (("baseline", baseline), ("candidate", candidate)):
        if any(
            not batch.get(name)
            for name in (
                "suite_sha256",
                "verifier_version",
                "harness_sha256",
                "evidence_mode",
                "model",
            )
        ):
            compatibility.append(f"{label}_missing_identity")
    if baseline.get("evidence_mode") not in EVIDENCE_MODES:
        compatibility.append("unknown_evidence_mode")
    if not baseline.get("case_ids") or not candidate.get("case_ids"):
        compatibility.append("empty_case_selection")
    left = {row["case_id"]: row for row in baseline["results"]}
    right = {row["case_id"]: row for row in candidate["results"]}
    duplicates = {
        label: [k for k, n in Counter(row["case_id"] for row in batch["results"]).items() if n > 1]
        for label, batch in (("baseline", baseline), ("candidate", candidate))
    }
    ids = sorted(set(baseline["case_ids"]) | set(candidate["case_ids"]) | set(left) | set(right))
    rows = []
    for ident in ids:
        a, b = left.get(ident), right.get(ident)
        status = (
            "incompatible"
            if compatibility
            else "missing"
            if a is None or b is None
            else "invalid"
            if a.get("invalid") or b.get("invalid")
            else "matched"
        )
        if ident in duplicates["baseline"] + duplicates["candidate"]:
            status = "invalid"
        if (a is not None and ident not in baseline["case_ids"]) or (
            b is not None and ident not in candidate["case_ids"]
        ):
            status = "invalid"
        if (
            a is not None
            and b is not None
            and (
                not a.get("case_sha256")
                or a.get("case_sha256") != b.get("case_sha256")
                or not isinstance(a.get("checks"), dict)
                or not isinstance(b.get("checks"), dict)
                or a.get("constraint_failures") is None
                or b.get("constraint_failures") is None
            )
        ):
            status = "invalid"
        rows.append(
            {
                "case_id": ident,
                "status": status,
                "baseline_failures": a.get("constraint_failures") if a else None,
                "candidate_failures": b.get("constraint_failures") if b else None,
                "regressions": [
                    k for k, v in b["checks"].items() if v is False and a["checks"].get(k) is True
                ]
                if status == "matched"
                else None,
                "improvements": [
                    k for k, v in b["checks"].items() if v is True and a["checks"].get(k) is False
                ]
                if status == "matched"
                else None,
                "baseline_metrics": a.get("metrics") if a else None,
                "candidate_metrics": b.get("metrics") if b else None,
            }
        )
    return {
        "compatibility_errors": compatibility,
        "duplicate_cases": duplicates,
        "cases": rows,
        "note": "No blended score. Failed critical constraints and invalid/missing cases remain explicit.",
    }


def upload_experiment(
    batch: dict, manifest: dict, client, dataset_name: str, experiment_prefix: str
):
    """Explicit external write: publish already measured local outputs, never rerun providers.

    SDK contract checked against langsmith==0.14.16. Root trace latency measures upload
    lookup only; measured workflow/tool latency remains in outputs.metrics.
    """
    if batch["suite_sha256"] != sha256(canonical(manifest)):
        raise ValueError("run and case manifest differ")
    if batch.get("evidence_mode") not in EVIDENCE_MODES:
        raise ValueError("unknown evidence mode")
    results = batch["results"]
    cases = {c["id"]: c for c in manifest["cases"]}
    if len({r["case_id"] for r in results}) != len(results) or any(
        r.get("invalid") for r in results
    ):
        raise ValueError("invalid or duplicate runs must not be uploaded as an experiment")
    if set(batch["case_ids"]) != {r["case_id"] for r in results}:
        raise ValueError("missing case runs must not be silently omitted from an experiment")
    for result in results:
        case = cases[result["case_id"]]
        if result["case_sha256"] != sha256(canonical(case)) or verify(case, result) != {
            name: result[name] for name in ("checks", "constraint_failures", "passed")
        }:
            raise ValueError("saved run verifier results do not match recorded observations")
    from langsmith.utils import LangSmithNotFoundError

    try:
        dataset = client.read_dataset(dataset_name=dataset_name)
    except LangSmithNotFoundError:
        dataset = client.create_dataset(
            dataset_name=dataset_name, metadata={"suite_sha256": batch["suite_sha256"]}
        )
    existing = list(client.list_examples(dataset_id=dataset.id))
    wanted = {r["case_id"] for r in results}
    if existing:
        if {e.inputs["case_id"] for e in existing} != set(cases) or any(
            (e.metadata or {}).get("suite_sha256") != batch["suite_sha256"]
            or e.outputs != {"case": cases[e.inputs["case_id"]]}
            for e in existing
        ):
            raise ValueError("existing LangSmith dataset does not match frozen suite")
    else:
        client.create_examples(
            dataset_id=dataset.id,
            examples=[
                {
                    "inputs": {"case_id": ident},
                    "outputs": {"case": case},
                    "metadata": {
                        "case_id": ident,
                        "suite_sha256": batch["suite_sha256"],
                        "verifier_version": VERIFIER_VERSION,
                    },
                }
                for ident, case in cases.items()
            ],
        )
        existing = list(client.list_examples(dataset_id=dataset.id))
    by_id = {r["case_id"]: r for r in results}

    def recorded_target(inputs: dict) -> dict:
        return by_id[inputs["case_id"]]

    def constraints(outputs: dict) -> dict:
        return {
            "results": [
                {"key": name, "score": int(passed)}
                for name, passed in outputs["checks"].items()
                if passed is not None
            ]
        }

    return client.evaluate(
        recorded_target,
        data=[e for e in existing if e.inputs["case_id"] in wanted],
        evaluators=[constraints],
        max_concurrency=0,
        experiment_prefix=experiment_prefix,
        metadata={k: v for k, v in batch.items() if k != "results"},
        description="Recorded whole-workflow observations; root latency is upload lookup, not agent latency. No owner ratings or simulator acceptance.",
    )
