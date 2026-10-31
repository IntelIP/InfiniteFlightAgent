"""Summarize an eval run's failures for review (no model or API calls).

    uv run python evals/triage.py artifacts/evals/<stamp>/results.jsonl [--regrade]

--regrade re-scores the saved transcripts with the current grader in run_eval.py.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval import DATASET, grade  # noqa: E402


def main() -> None:
    path = Path(sys.argv[1])
    regrade = "--regrade" in sys.argv
    cases = {c["id"]: c for c in map(json.loads, DATASET.read_text().splitlines()) if c}
    runs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    by_check, by_category, failures = Counter(), defaultdict(lambda: [0, 0]), []
    for run in runs:
        checks = grade(cases[run["id"]], run) if regrade else run["checks"]
        bad = [k for k, v in checks.items() if v is False]
        by_category[run["category"]][1] += 1
        if not bad:
            by_category[run["category"]][0] += 1
            continue
        by_check.update(bad)
        failures.append((run, bad))
    passed = sum(v[0] for v in by_category.values())
    print(f"{passed}/{len(runs)} cases pass{' (regraded)' if regrade else ''}")
    print("failing checks:", dict(by_check.most_common()))
    print("by category:", {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_category.items())})
    for run, bad in failures:
        exp = cases[run["id"]]["expected"]
        first = next((t["text"] for t in run["transcript"] if t["role"] == "assistant"), "")
        print(f"\n### {run['id']} {run['category']} FAILED {bad}")
        print("PROMPT:", run["prompt"])
        print(f"EXPECTED: {exp['first_action']} clarify={exp['clarify_topics']} legs={exp['legs']}")
        print(
            "TOOLS:",
            run["turn_tools"][:3],
            "| dispatches:",
            [(d.get("origin"), d.get("destination")) for d in run["dispatches"]],
        )
        if run["error"]:
            print("ERROR:", run["error"])
        print("FIRST REPLY:", first[:500].replace("\n", " "))


if __name__ == "__main__":
    main()
