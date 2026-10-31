"""Record local checks and explicit live acceptance gaps on every invocation."""

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "artifacts/validation"
out.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
result = {
    "schemaVersion": "tabellio-validator-evidence/v0.1",
    "validatorId": "simbrief-workflow",
    "status": "blocked",
    "summary": "Live generation, neo response, two provider legs, authentication and exact commit remain unverified.",
    "metrics": [],
    "artifacts": [],
    "cost": {"telemetry": "not_applicable", "usd": None, "modelCalls": None, "toolCalls": None},
}
try:
    paths = [
        Path(n)
        for n in subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root, text=True
        ).splitlines()
    ]
    source = {
        str(p): hashlib.sha256((root / p).read_bytes()).hexdigest()
        for p in paths
        if (root / p).is_file() and not str(p).startswith("docs/evidence/")
    }
    candidate = out / f"{stamp}-candidate.json"
    candidate.write_text(json.dumps(source, sort_keys=True, indent=2) + "\n")
    checks = [
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"],
        ["bash", "scripts/check-dead-code.sh"],
    ]
    logs = []
    for argv in checks:
        completed = subprocess.run(argv, cwd=root, text=True, capture_output=True, timeout=120)
        logs.append(
            {
                "argv": argv,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
    log = out / f"{stamp}-checks.json"
    log.write_text(json.dumps(logs, indent=2) + "\n")
    passed = all(x["exit_code"] == 0 for x in logs)
    if not passed:
        result["status"] = "failed"
        result["summary"] = "Local checks failed; live acceptance also remains unverified."
    for p in [candidate, log]:
        data = p.read_bytes()
        result["artifacts"].append(
            {
                "name": p.name,
                "uri": "urn:ifdispatcher:evidence:" + p.name,
                "digest": hashlib.sha256(data).hexdigest(),
                "mediaType": "application/json",
                "bytes": len(data),
            }
        )
    result["metrics"] = [{"name": "local_checks_pass", "value": int(passed), "unit": "boolean"}]
except Exception as exc:
    result["status"] = "failed"
    result["summary"] = f"Validator could not finish: {type(exc).__name__}"
finally:
    content = json.dumps(result, indent=2) + "\n"
    (out / f"{stamp}-result.json").write_text(content)
    (out / "latest.json").write_text(content)
print(result["status"] + ": " + result["summary"])
sys.exit(0 if result["status"] == "passed" else 1)
