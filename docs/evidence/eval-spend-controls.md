# FlightAware evaluation spend controls — November 1, 2026

Status: **passed for the local working-tree change**, not a deployment or whole-product release.

Implemented replay-by-default, frozen clocks, strict missing-fixture handling, explicit live
sample selection, a $1 default batch ceiling with reserve/settle accounting, endpoint-specific
list pricing, raw-response recording, and a seven-day airport metadata cache. Research tests
stop at dispatch approval and block SimBrief actions. The live E2E runner requires explicit
`--live --ids` and uses the same FlightAware allowance.

GPT-6-Astra authored 12 synthetic cases and deterministic fixture builders. All 99 fixture
contracts and 12 synthetic scenario checks passed. Historical import recovered 87 partial
snapshots: 13 original cases remain uncovered and 24 recovered cases have metadata gaps.
They are labeled derived recordings and kept Git-ignored. Synthetic scenarios are separate.

Verification:

- `pytest tests/test_eval_costs.py tests/test_flights.py tests/test_agent_workflow.py -q`: 35 passed.
- `python evals/fixtures/validate_assets.py`: 99 contracts, 12 scenarios passed.
- Ruff over src/tests/scripts/evals, pinned dead-code check and `git diff --check`: passed.
- Real agent replay `eval-replay-20261101T181309Z`: SYNTH-001 and SYNTH-008 passed, no missing
  requests, 10 fixture hits, no FlightAware HTTP calls, $0 FlightAware cost. The DST transcript
  correctly distinguished 01:30 EDT and 01:30 EST. Agent model: existing GPT-6 Luna through
  ChatGPT plan capacity; no separate model-dollar telemetry. Final grounding checks also
  passed against the retained transcripts.

Local evidence and candidate hashes: `artifacts/validation/eval-spend-controls/result.json`.
Raw model transcripts: `artifacts/evals/20261101T181309Z/results.jsonl` (Git-ignored).

No new live FlightAware calls, SimBrief generation, deployment, commit or push was performed.
The full test suite was not run: machine guidance requested targeted checks due to memory
pressure and other running work. These results establish controlled replay and budget
behavior, not fresh schedule availability or complete historical replay coverage. The
FlightAware cap is per evaluation process, not an account-wide monthly spending limit.

See [the evaluation guide](../../evals/README.md) for commands and pricing assumptions.
