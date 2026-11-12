"""Run frozen v0.4.5 contracts and pinned simulation references without provider/model calls.

Optional --upload publishes recorded software results to existing LangSmith access; it
never generates a flight or represents source-port agreement as simulator verification.
"""

import argparse
import hashlib
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(module_file, manifest_file, reference_file):
    manifest = json.loads(manifest_file.read_text())
    reference = json.loads(reference_file.read_text())
    spec = importlib.util.spec_from_file_location("thrust_under_test", module_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = []
    for case in manifest["cases"]:
        try:
            result = module.estimate_takeoff_n1(**case["input"])
            expected = case["expected"]
            passed = result["status"] == expected["status"] and (
                "engine" not in expected
                or result.get("data", {}).get("engine") == expected["engine"]
            )
            rows.append(
                dict(case, result=result, passed=passed, evidence_class="software-contract")
            )
        except Exception as exc:
            rows.append(dict(case, error=f"{type(exc).__name__}: {exc}", passed=False))
    for case in reference["cases"]:
        actual = module.fbw_leap1a26_n1(
            case["pressure_altitude_ft"],
            case["oat_c"],
            case["flex_c"],
            case["packs"],
            case["nacelle_anti_ice"],
            case["wing_anti_ice"],
        )
        error = abs(actual - case["source_n1_percent"])
        rows.append(
            {
                "id": case["id"],
                "input": case,
                "actual_n1_percent": actual,
                "absolute_error": error,
                "passed": error <= reference["raw_tolerance_n1_percentage_points"],
                "evidence_class": "pinned-simulation-source",
            }
        )
    return {
        "suite": manifest["id"],
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "fixture_clock": manifest["clock_utc"],
        "baseline_commit": manifest["baseline"],
        "module_file": str(module_file),
        "worktree_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "worktree_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
        ),
        "inputs_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (manifest_file, reference_file, Path(__file__))
        },
        "module_sha256": hashlib.sha256(module_file.read_bytes()).hexdigest(),
        "provider_calls": {"browserbase": 0, "flightaware": 0, "model": 0},
        "limitations": reference["gaps"],
        "results": rows,
    }


def upload(report):
    from langsmith import Client, evaluate
    from ifdispatcher.config import setting

    client = Client(api_key=setting("LANGSMITH_API_KEY"))
    fixture_id = hashlib.sha256(
        json.dumps(report["inputs_sha256"], sort_keys=True).encode()
    ).hexdigest()
    name = "Infinite Flight thrust v045 " + fixture_id[:12]
    dataset = (
        client.read_dataset(dataset_name=name)
        if client.has_dataset(dataset_name=name)
        else client.create_dataset(name)
    )
    examples = list(client.list_examples(dataset_id=dataset.id))
    by_id = {e.inputs["id"]: e for e in examples}
    if examples and (
        set(by_id) != {row["id"] for row in report["results"]}
        or any(
            by_id[row["id"]].inputs != {"id": row["id"], "input": row["input"]}
            for row in report["results"]
        )
    ):
        raise ValueError("LangSmith examples differ from the frozen numerical fixtures")
    for row in report["results"]:
        if row["id"] not in by_id:
            by_id[row["id"]] = client.create_example(
                inputs={"id": row["id"], "input": row["input"]}, dataset_id=dataset.id
            )
    rows = {row["id"]: row for row in report["results"]}
    results = evaluate(
        lambda inputs: rows[inputs["id"]],
        data=[by_id[row["id"]] for row in report["results"]],
        evaluators=[
            lambda run: {
                "key": "software_case_passed",
                "score": int(run.outputs["passed"]),
            }
        ],
        experiment_prefix="v045-thrust-" + report["module_sha256"][:8],
        metadata={k: v for k, v in report.items() if k != "results"},
        client=client,
        max_concurrency=1,
    )
    results.wait()
    return {"experiment": results.experiment_name, "url": results.url}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module-file", type=Path, default=ROOT / "src/ifdispatcher/thrust.py")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    report = run(
        args.module_file,
        ROOT / "evals/thrust_cases_v045.json",
        ROOT / "docs/research/evidence/thrust-v045-reference.json",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"{sum(row['passed'] for row in report['results'])}/{len(report['results'])} software cases passed; zero provider/model calls"
    )
    if args.upload:
        print(json.dumps(upload(report)))
    raise SystemExit(int(not all(row["passed"] for row in report["results"])))


if __name__ == "__main__":
    main()
