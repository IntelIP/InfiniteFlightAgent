"""Workflow evaluation baseline: real graph/Store, scripted models, no external writes."""

import copy
import json
import socket
from importlib.metadata import version
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
from run_workflow_replay import run_case  # noqa: E402
from workflow_evaluations import (  # noqa: E402
    MANIFEST,
    VERIFIER_VERSION,
    canonical,
    compare,
    load_manifest,
    sha256,
    source_identity,
    upload_experiment,
    verify,
)


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


@pytest.fixture(scope="module")
def runs(manifest):
    # Any escape from controlled providers/isolated storage is a test failure, including
    # ambient LangSmith tracing and DATABASE_URL selection. No credentials are loaded.
    with pytest.MonkeyPatch.context() as patcher:

        def forbidden(*args, **kwargs):
            raise AssertionError("baseline test must not use the network")

        patcher.setattr(socket.socket, "connect", forbidden)
        patcher.setenv("DATABASE_URL", "postgresql://forbidden.invalid/production")
        patcher.setenv("LANGSMITH_TRACING", "true")
        return {case["id"]: run_case(case, manifest) for case in manifest["cases"]}


def batch(manifest, runs):
    return {
        "suite_sha256": sha256(canonical(manifest)),
        "verifier_version": VERIFIER_VERSION,
        "harness_sha256": "controlled-test-harness",
        "evidence_mode": "scripted-controlled",
        "model": "scripted",
        "effort": None,
        "case_ids": list(runs),
        "results": list(runs.values()),
    }


def test_frozen_manifest_and_worktree_identity(manifest, tmp_path):
    identity = source_identity()
    assert identity["commit"] and identity["source_sha256"]
    assert identity["langsmith_version"] == version("langsmith")
    assert "src/ifdispatcher/agent.py" in identity["source_files"]
    duplicate = copy.deepcopy(manifest)
    duplicate["cases"].append(duplicate["cases"][0])
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(duplicate))
    with pytest.raises(ValueError, match="unique"):
        load_manifest(path)
    changed = copy.deepcopy(manifest)
    changed["fixture"]["sha256"] = "not-the-frozen-fixture"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="digest"):
        load_manifest(path)
    assert MANIFEST.exists()


def test_foundation_cases_complete_and_record_honest_metrics(manifest, runs):
    for case in manifest["cases"][:6]:
        run = runs[case["id"]]
        assert run["passed"], (case["id"], run["constraint_failures"], run["error"])
        assert not run["invalid"]
        assert run["metrics"]["model_usage"] is None
        assert run["metrics"]["owner_ratings"] is None
        assert run["metrics"]["flightaware_requests"] == 0
        assert run["metrics"]["browserbase_sessions"] == 0
        assert run["metrics"]["tool_calls"] > 0
    assert len(runs["WF-004"]["state"]) == 2
    assert len(runs["WF-003"]["provider_attempts"]) == 2
    assert len(runs["WF-003"]["clicks"]) == 1
    assert runs["WF-003"]["metrics"]["tool_calls_by_name"]["generate_in_simbrief"] == 3
    assert runs["WF-002"]["state"] == []


@pytest.mark.parametrize(
    "change,failed",
    [
        (lambda r: r["state"][0]["request"].update(destination="KLAX"), "intent_input_identity"),
        (lambda r: r["observations"][-1].update(approved=[]), "approval_bounds"),
        (lambda r: r["clicks"].append(r["clicks"][0]), "duplicate_generate_prevented"),
        (lambda r: r["state"][0].update(computed_sha256="corrupted"), "correlated_immutable_ofps"),
        (
            lambda r: r["observations"][-1]["snapshot_hashes"].append(
                (["WF-001", "1", 1], "changed")
            ),
            "correlated_immutable_ofps",
        ),
        (lambda r: r.update(state=[]), "retained_legs"),
    ],
)
def test_end_state_oracles_reject_unsafe_outcomes(manifest, runs, change, failed):
    run = copy.deepcopy(runs["WF-001"])
    change(run)
    assert failed in verify(manifest["cases"][0], run)["constraint_failures"]


def test_approval_accepts_equivalent_utc_timestamp(manifest, runs):
    run = copy.deepcopy(runs["WF-001"])
    run["approvals"][0]["args"]["departure_utc"] = "2026-11-08T12:00:00+00:00"
    assert verify(manifest["cases"][0], run)["checks"]["approval_bounds"]
    run["approvals"][0]["args"]["departure_utc"] = "2026-11-08T12:01:00+00:00"
    assert not verify(manifest["cases"][0], run)["checks"]["approval_bounds"]


def test_snapshot_must_postdate_saved_generate_claim_with_one_minute_tolerance(manifest, runs):
    run = copy.deepcopy(runs["WF-001"])
    # The controlled snapshot was generated at 11:00:01Z. BUILD-04 permits one minute.
    run["state"][0]["meta"]["generation"]["at"] = "2026-11-08T11:01:01+00:00"
    assert verify(manifest["cases"][0], run)["checks"]["correlated_immutable_ofps"]
    run["state"][0]["meta"]["generation"]["at"] = "2026-11-08T11:01:02Z"
    assert not verify(manifest["cases"][0], run)["checks"]["correlated_immutable_ofps"]


def test_targeted_regressions_have_truthful_failure_observations(runs):
    revision = runs["WF-007"]
    assert len(revision["state"]) == 1
    assert revision["state"][0]["snapshot"]
    assert len(revision["clicks"]) == 1
    # The old base raises; the candidate must recover with an explicit unsupported result.
    if revision["error"]:
        assert revision["error"]["type"] == "ValueError"
        assert "revision_failure_recovery" in revision["constraint_failures"]
        assert revision["metrics"]["tool_calls_by_name"]["finalize_dispatch"] == 1
    else:
        assert revision["checks"]["revision_failure_recovery"]
    provider = runs["WF-008"]
    assert provider["clicks"] == []
    assert len(provider["provider_attempts"]) == 1
    assert len(provider["state"]) == 1 and provider["state"][0]["snapshot"] is None
    assert provider["error"] is None
    output = [t["output"] for t in provider["tool_results"] if t["name"] == "generate_in_simbrief"][
        0
    ]
    assert output["clicked"] is False
    if output.get("reason_code"):
        assert provider["checks"]["provider_failure_contract"]
    else:
        assert "provider_failure_contract" in provider["constraint_failures"]


def test_comparison_surfaces_missing_invalid_incompatible_and_critical_failure(manifest, runs):
    before = batch(manifest, runs)
    after = copy.deepcopy(before)
    after["results"] = after["results"][:-1]
    after["results"][0]["invalid"] = True
    rows = {r["case_id"]: r for r in compare(before, after)["cases"]}
    assert rows["WF-008"]["status"] == "missing"
    assert rows["WF-001"]["status"] == "invalid"
    assert rows["WF-002"]["status"] == "matched"
    after = copy.deepcopy(before)
    after["results"][0]["checks"]["approval_bounds"] = False
    assert compare(before, after)["cases"][0]["regressions"] == ["approval_bounds"]
    after["results"][0]["case_sha256"] = "different-case"
    assert compare(before, after)["cases"][0]["status"] == "invalid"
    after["evidence_mode"] = "real-model-replay"
    assert "evidence_mode" in compare(before, after)["compatibility_errors"]
    after = copy.deepcopy(before)
    after["results"].append(after["results"][0])
    assert compare(before, after)["duplicate_cases"]["candidate"] == ["WF-001"]


def test_upload_uses_installed_experiment_contract_and_never_reruns_workflow(manifest, runs):
    from langsmith.utils import LangSmithNotFoundError

    class Client:
        examples = []

        def read_dataset(self, **kwargs):
            raise LangSmithNotFoundError("not yet created")

        def create_dataset(self, **kwargs):
            self.dataset = kwargs
            return SimpleNamespace(id="controlled-dataset")

        def list_examples(self, **kwargs):
            return self.examples

        def create_examples(self, *, examples, **kwargs):
            self.examples = [SimpleNamespace(**e) for e in examples]

        def evaluate(self, target, *, data, evaluators, **kwargs):
            assert kwargs["max_concurrency"] == 0
            assert kwargs["metadata"]["evidence_mode"] == "scripted-controlled"
            assert len(data) == len(runs)
            output = target(data[0].inputs)
            assert output is runs[data[0].inputs["case_id"]]
            feedback = evaluators[0](output)
            assert all(row["score"] in (0, 1) for row in feedback["results"])
            assert not any("owner" in row["key"] for row in feedback["results"])
            return "controlled-experiment"

    client = Client()
    assert (
        upload_experiment(batch(manifest, runs), manifest, client, "frozen-suite", "baseline")
        == "controlled-experiment"
    )
    assert len(client.examples) == len(manifest["cases"])
    incomplete = batch(manifest, runs)
    incomplete["results"] = incomplete["results"][:-1]
    with pytest.raises(ValueError, match="missing"):
        upload_experiment(incomplete, manifest, client, "frozen-suite", "bad")
    stale = copy.deepcopy(batch(manifest, runs))
    stale["results"][0]["checks"]["approval_bounds"] = False
    with pytest.raises(ValueError, match="recorded observations"):
        upload_experiment(stale, manifest, client, "frozen-suite", "bad")


def test_agent_and_calibration_clock_are_frozen(manifest, monkeypatch):
    from ifdispatcher import agent, operations

    build = agent.build_agent
    observed = []

    def capture(*args, **kwargs):
        observed.append((agent.current_time.invoke({}), operations.datetime.now().isoformat()))
        return build(*args, **kwargs)

    monkeypatch.setattr(agent, "build_agent", capture)
    assert run_case(manifest["cases"][0], manifest)["passed"]
    assert observed == [
        (
            {"utc": "2026-11-08T11:00+00:00", "local": "Sunday 2026-11-08 06:00 EST"},
            "2026-11-08T11:00:00",
        )
    ]
