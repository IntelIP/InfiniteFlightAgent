"""Release scenarios use actual MCP transport, controlled providers and isolated storage."""

import copy
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
from run_workflow_replay import run_case  # noqa: E402
from workflow_evaluations import compare, load_manifest, verify  # noqa: E402


@pytest.fixture(scope="module")
def release_manifest():
    return load_manifest(ROOT / "evals/workflow_cases_v044.json")


@pytest.fixture(scope="module")
def mcp_batch(tmp_path_factory):
    return run_mcp_batch(
        tmp_path_factory.mktemp("release-mcp"), ROOT / "evals/workflow_cases_v044.json"
    )


@pytest.fixture(scope="module")
def trip_control_batch(tmp_path_factory):
    return run_mcp_batch(
        tmp_path_factory.mktemp("trip-control-mcp"), ROOT / "evals/workflow_cases_v050.json"
    )


def run_mcp_batch(directory, manifest):
    production = directory / "production"
    production.mkdir()
    marker = production / "do-not-change"
    marker.write_text("retained production state")
    # The subprocess keeps the production FastMCP singleton separate from test_remote.
    # Fail on any external DNS or socket access, even if ambient credentials are present.
    (directory / "sitecustomize.py").write_text(
        "import socket\n"
        "def local(host):\n"
        "    if host not in ('127.0.0.1', 'localhost', '::1', None):\n"
        "        raise AssertionError('controlled MCP replay attempted external network access')\n"
        "connect = socket.socket.connect\n"
        "connect_ex = socket.socket.connect_ex\n"
        "getaddrinfo = socket.getaddrinfo\n"
        "def guarded_connect(self, address):\n"
        "    if isinstance(address, tuple): local(address[0])\n"
        "    return connect(self, address)\n"
        "def guarded_connect_ex(self, address):\n"
        "    if isinstance(address, tuple): local(address[0])\n"
        "    return connect_ex(self, address)\n"
        "def guarded_getaddrinfo(host, *args, **kwargs):\n"
        "    local(host)\n"
        "    return getaddrinfo(host, *args, **kwargs)\n"
        "socket.socket.connect = guarded_connect\n"
        "socket.socket.connect_ex = guarded_connect_ex\n"
        "socket.getaddrinfo = guarded_getaddrinfo\n"
    )
    output = directory / "results.json"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(directory), str(ROOT / "src"))),
        "IFD_DATA_DIR": str(production),
        "DATABASE_URL": "postgresql://forbidden.invalid/production",
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_API_KEY": "controlled-sentinel-not-a-secret",
        "BROWSERBASE_API_KEY": "controlled-sentinel-not-a-secret",
        "AEROAPI_KEY": "controlled-sentinel-not-a-secret",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "evals/run_workflow_replay.py"),
            "run",
            "--manifest",
            str(manifest),
            "--mcp",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    batch = json.loads(output.read_text()) if output.exists() else None
    assert result.returncode == 0, (
        [
            (row["case_id"], row["constraint_failures"], row["error"])
            for row in batch["results"]
            if row["invalid"] or not row["passed"]
        ]
        if batch
        else result.stdout + result.stderr
    )
    assert list(production.iterdir()) == [marker]
    assert marker.read_text() == "retained production state"
    return batch


def test_release_matrix_preserves_original_cases_and_completes_over_mcp(
    release_manifest, mcp_batch
):
    original = load_manifest()
    assert release_manifest["cases"][:8] == original["cases"]
    assert mcp_batch["case_ids"] == [case["id"] for case in release_manifest["cases"]]
    for row in mcp_batch["results"]:
        assert row["passed"] and not row["invalid"], row["case_id"]
        assert row["metrics"]["transport"] == "mcp-http"
        assert row["metrics"]["flightaware_requests"] == 0
        assert row["metrics"]["browserbase_sessions"] == 0
        assert row["metrics"]["owner_ratings"] is None
    runs = {row["case_id"]: row for row in mcp_batch["results"]}
    assert runs["WF-011"]["checks"]["restart_recovery"]
    assert len(runs["WF-011"]["mcp_saved"]["legs"]) == 2
    revised = runs["WF-025"]["state"]
    assert {row["request"]["revision"] for row in revised} == {1, 2}
    assert all(row["snapshot"] and row["meta"]["briefing"] for row in revised)


def test_trip_control_suite_over_mcp(trip_control_batch):
    """INT-416/417 scenarios: cancel at approval/before/after the click, deadline, restart."""
    manifest = load_manifest(ROOT / "evals/workflow_cases_v050.json")
    assert trip_control_batch["case_ids"] == [c["id"] for c in manifest["cases"]]
    runs = {row["case_id"]: row for row in trip_control_batch["results"]}
    for row in runs.values():
        assert row["passed"] and not row["invalid"], (row["case_id"], row["constraint_failures"])
        assert row["metrics"]["transport"] == "mcp-http"
        assert row["metrics"]["flightaware_requests"] == 0
        assert row["metrics"]["browserbase_sessions"] == 0
        assert row["cancelled"] is True
    # Completed work survives cancellation; uncertain generation is reported, never repeated.
    assert runs["WF-030"]["state"][0]["meta"]["briefing"].startswith("**SPAWN:**")
    assert len(runs["WF-032"]["provider_attempts"]) == 1
    assert runs["WF-031"]["clicks"] == [] and runs["WF-033"]["clicks"] == []


def test_trip_control_cases_are_invalid_without_mcp():
    manifest = load_manifest(ROOT / "evals/workflow_cases_v050.json")
    run = run_case(manifest["cases"][0], manifest)
    assert run["invalid"] and "requires --mcp" in run["invalid_reasons"][0]


@pytest.mark.parametrize(
    "corruption,failed",
    [
        ("duplicate-click", "duplicate_generate_prevented"),
        ("lost-snapshot", "retained_legs"),
        ("wrong-route", "retained_route_evidence"),
        ("approval-bypass", "approval_bounds"),
        ("lost-briefing", "completion"),
        ("mcp-lost-snapshot", "mcp_retained_results"),
        ("mcp-lost-briefing", "mcp_retained_results"),
        ("restart-lost-reply", "restart_recovery"),
    ],
)
def test_release_oracles_reject_unsafe_final_states(
    release_manifest, mcp_batch, corruption, failed
):
    case_id = "WF-011" if corruption.startswith("restart") else "WF-017"
    case = next(case for case in release_manifest["cases"] if case["id"] == case_id)
    row = copy.deepcopy(next(row for row in mcp_batch["results"] if row["case_id"] == case_id))
    if corruption == "duplicate-click":
        row["clicks"].append(copy.deepcopy(row["clicks"][0]))
    elif corruption == "lost-snapshot":
        row["state"][0]["snapshot"] = None
    elif corruption == "wrong-route":
        row["state"][0]["snapshot"]["data"]["flight_route"] = "DCT"
    elif corruption == "approval-bypass":
        next(o for o in row["observations"] if o["request_keys"])["approved"] = []
    elif corruption == "lost-briefing":
        row["state"][0]["meta"]["briefing"] = ""
    elif corruption == "mcp-lost-snapshot":
        row["mcp_saved"]["legs"][0]["snapshot_sha256"] = None
    elif corruption == "mcp-lost-briefing":
        row["mcp_saved"]["legs"][0]["briefing_markdown"] = ""
    elif corruption == "restart-lost-reply":
        row["recovered"]["reply"] = "A different conversation"
    result = verify(case, row)
    assert not result["passed"]
    assert failed in result["constraint_failures"]


def test_unavailable_fixture_cannot_be_reported_as_a_matched_success(
    release_manifest, monkeypatch, tmp_path
):
    missing = copy.deepcopy(release_manifest)
    missing["fixture"]["path"] = str(tmp_path / "missing-ofp.json")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(missing))
    with pytest.raises(FileNotFoundError):
        load_manifest(path)

    def forbidden(*args, **kwargs):
        raise AssertionError("missing fixture must not contact a provider")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    case = copy.deepcopy(release_manifest["cases"][12])
    case["script"] = [
        {"tool": "simbrief_airframes", "args": {"aircraft": "ZZZZ"}},
        {"text": "No controlled airframe fixture is available."},
    ]
    run = run_case(case, release_manifest)
    assert run["invalid"] and run["invalid_reasons"]
    assert run["clicks"] == [] and run["state"] == []
    batch = {
        "suite_sha256": "same-suite",
        "verifier_version": "same-verifier",
        "harness_sha256": "same-harness",
        "evidence_mode": "scripted-controlled",
        "model": "scripted",
        "effort": None,
        "case_ids": [case["id"]],
        "results": [run],
    }
    compared = compare(batch, copy.deepcopy(batch))
    assert compared["cases"][0]["status"] == "invalid"
    assert compared["cases"][0]["regressions"] is None
