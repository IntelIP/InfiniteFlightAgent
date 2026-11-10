# Cost-controlled evaluations

Research evaluations now use local FlightAware fixtures by default. The agent still runs
through the real tools and uses ChatGPT plan capacity. FlightAware cost is **$0 in replay**.
Missing fixture requests invalidate the case; they never enable network fallback. Replay
freezes the tool and flight-data clock, stops at dispatch approval, disables SimBrief actions,
and keeps dispatch state in a temporary local store even when deployment credentials are set.

```sh
# Offline provider data, live model: GPT-6-Astra-authored synthetic regression suite
uv run python evals/run_eval.py

# Historical filtered snapshots, where reconstructable
uv run python evals/fixtures/build_recordings.py --source-root artifacts/evals
uv run python evals/run_eval.py --dataset evals/dispatch_prompts.jsonl --ids IFD-001

# Explicit live sample; $1 limit covers the WHOLE batch, not each case
uv run python evals/run_eval.py --dataset evals/dispatch_prompts.jsonl --live --ids IFD-001,IFD-005 --budget-usd 1.00
```

Live runs save responses under `artifacts/evals/<timestamp>/recordings/`. Reuse that directory
with `--fixture-dir` and the same original case IDs. Recordings retain the initial clock,
request parameters, response status and JSON, without request credentials. Cached airport
responses are marked as cached. Keep real and derived provider observations local; recording
storage is ignored by Git. Do not represent historical or synthetic observations as live data.

The default synthetic suite contains deliberately invented flights and gates shaped like the
observed responses. Its cases are authored by GPT-6-Astra; deterministic code materializes the
relationships and edge cases. Existing 100 prompts remain unchanged. Historical normalized
outputs lost fields, query arguments and pre-filter rows, so reconstructed snapshots are a
separate, incomplete test source—not raw recordings or proof of full historical coverage.
See `fixtures/README.md` and `fixtures/recording_coverage.json`.

## Budget and reporting

The live FlightAware budget reserves endpoint price × maximum requested pages **before**
sending a request. Calls from concurrent tools share a lock and one batch allowance. Successful
responses settle against reported pages; uncertain failures retain their reservation. Cached
responses cost zero. Budget rejection stops the batch. Unknown endpoints have no assumed
price and fail closed. This is a per-process evaluation cap, not an account-wide monthly cap.

Reports include actual list-price usage, held amounts, individual HTTP requests/pages,
cache hits, fixture misses, fixture provenance kind, and invalid cases excluded from scores.
Rates checked 2026-11-01 against [FlightAware's published fees](https://www.flightaware.com/commercial/aeroapi/):
route search $0.050/page, airport metadata $0.015/page, flight identity/departure boards
$0.005/page. Credits and discounts are not included; provider billing remains authoritative.
Model usage and Browserbase/SimBrief costs are not covered by this FlightAware ceiling.

Airport metadata is cached on disk for seven days, at
`~/.cache/InfiniteFlightDispatcher/airports/` by default. Override with
`IFD_AIRPORT_CACHE_DIR`; set it to `disabled` to bypass disk caching. Gates, flight schedules,
and equipment retain only the existing short memory cache.

`run_e2e.py` is deliberately live-only because it generates real SimBrief plans. It now
requires both `--live` and explicit `--ids`, and shares the FlightAware budget mechanism.
Its other provider charges and account writes still need explicit task authorization.

## Verification

```sh
uv run python evals/fixtures/validate_assets.py
uv run pytest tests/test_eval_costs.py tests/test_flights.py tests/test_agent_workflow.py -q
```

These checks prove replay/normalization and spend controls against controlled responses.
They do not prove provider availability or current flight schedules. Use a small explicit
live sample before releases or after changing the provider integration. Larger live runs
need an intentionally chosen list and budget; ordinary prompt changes use replay.


## Versioned whole-workflow baseline (INT-403)

`run_eval.py` remains the conversation/research evaluation that stops before approval.
`run_workflow_replay.py` extends the existing replay through approval, generation, parser,
immutable snapshots, retained legs and final briefing. It uses the actual Deep Agents graph,
LangGraph approval middleware, local SQLite Store and `observability.summarize`, using the
same scripted-model pattern as `tests/test_remote.py`. It adds no provider or model judge.

The default is entirely scripted. FlightAware/Browserbase calls, R2 uploads, production
stores, feedback writes and ambient LangSmith tracing are blocked or replaced with controlled
responses. A temporary local store and in-memory checkpointer are created per case even when
`DATABASE_URL` is set. These process-global provider patches make this a **sequential harness**;
do not run cases concurrently within one process.

```sh
# Scripted model and controlled providers; no model/provider calls or LangSmith writes
uv run python evals/run_workflow_replay.py run --output artifacts/evals/workflow-baseline.json

# Run the same frozen cases in the candidate checkout
uv run python evals/run_workflow_replay.py run --output artifacts/evals/workflow-candidate.json
uv run python evals/run_workflow_replay.py compare \
  artifacts/evals/workflow-baseline.json artifacts/evals/workflow-candidate.json \
  --output artifacts/evals/workflow-comparison.json

# Explicit model opt-in: GPT-6 Luna, low effort, controlled provider responses
uv run python evals/run_workflow_replay.py run --real-model --ids WF-007,WF-008 \
  --output artifacts/evals/workflow-model-candidate.json

uv run pytest tests/test_workflow_evaluations.py tests/test_remote.py -q
```

Run baseline and candidate with the **same harness, manifest, case selection and model
configuration** against their respective application source. Copy the evaluation files into
a base checkout when comparing an application change; source hashes will disclose that local
patch. Compare like evidence layers: scripted runs and real-model replay are incompatible.
The `run` command exits nonzero on any failed or invalid case. `compare` exits nonzero on
incompatibility, missing/invalid cases or newly regressed checks; persistent failures stay
visible in the report even when they are not new regressions.

`workflow_cases.json` freezes suite/case IDs, the UTC clock, seed OFP and provenance hashes,
verifier version, base commit, explicit dispatch inputs and expected outcomes. The seed is an
intentionally incomplete sanitized B38M parser fixture. The runner explicitly transforms its
identity/profile, fuel and feasibility fields into controlled synthetic responses. These are
not actual neo OFPs, provider observations or aircraft performance references. Changes to
cases/oracles require a new version/manifest identity; do not silently replace a baseline.

| Case | Required end state |
| --- | --- |
| WF-001 | Exact private-flight inputs, correlated snapshot and retained briefing |
| WF-002 | Rejected approval leaves no request, snapshot or Generate click |
| WF-003 | Pre-click mismatch can recover; duplicate Generate cannot click again; calibration keeps the same snapshot |
| WF-004 | Both legs remain separately identified and retained |
| WF-005 | Infeasibility remains explicit and takeoff thrust is withheld |
| WF-006 | Unsupported aircraft thrust remains unavailable |
| WF-007 | Unsupported alternate/cruise revision is refused without graph failure, new approval, new snapshot or regeneration |
| WF-008 | Explicit controlled SDK quota failure exposes a reason and next action, disables automatic retry and makes no click |

WF-007 and WF-008 are regression cases: the original base is expected to fail them. The quota
fixture is a constructed `browserbase.RateLimitError` with explicit quota evidence in its body;
it does not establish the cause of a historical exception with an empty/unknown body. Broad
scenario coverage, owner preference ratings, numeric quality thresholds, aircraft accuracy
and simulator acceptance are outside this foundation.

Each JSON batch records `suite_sha256`, `case_ids`, `verifier_version`, `fixture_clock`,
`base_commit`, and `source` (Git commit, dirty status, per-file SHA-256, combined source digest,
installed LangSmith version). A dirty run is worktree evidence, not exact-commit acceptance.
Each case includes its case digest, exact approval decisions, controlled provider fields/clicks,
observed requests/meta/raw snapshots, snapshot history, tool outputs, transcript and errors.
The verifier checks these recorded end states; it never trusts a tool's success label alone.

`checks` and `constraint_failures` report independent booleans; there is no blended score.
Metrics preserve tool calls by name, schema errors, clarification reply turns, assistant
question turns, measured tool/turn/whole-case latency, raw model usage metadata and provider
usage events. `clarification_turns` counts harness replies asking the model to proceed after
it ended without preparing a request; question marks are only an observable count, not a
semantic rating of unnecessary questions. No owner ratings are synthesized. Missing model
usage is `null`, real-model dollar cost is `null`, and known controlled-provider HTTP/session
counts and charges are zero. Tool outputs retain additive failure fields (`reason_code`,
`reason`, `next`, `automatic_retry_allowed`) without requiring them on older versions.

The comparison joins by case ID and case digest, requires matching suite/verifier/harness/evidence
mode/model/effort, and lists missing, invalid, duplicate and incompatible runs explicitly.
A product exception is a valid observed failure; an invalid run means the harness/input/report
cannot support a comparison. Manifest/fixture drift aborts before execution. Reports should
remain under ignored `artifacts/evals/` because they retain complete observations.

### Optional LangSmith experiment upload

The installed `langsmith==0.14.16` supports [`Client.evaluate`](https://docs.langchain.com/langsmith/evaluate-llm-application).
After separate authorization, publish a saved run with this explicit command:

```sh
uv run python evals/run_workflow_replay.py upload artifacts/evals/workflow-baseline.json \
  --dataset-name ifd-workflow-v1-FROZEN_MANIFEST_HASH --experiment-prefix baseline
uv run python evals/run_workflow_replay.py upload artifacts/evals/workflow-candidate.json \
  --dataset-name ifd-workflow-v1-FROZEN_MANIFEST_HASH --experiment-prefix candidate
```

This creates/reuses one frozen dataset and uses the SDK experiment API to publish **recorded
local outputs** and independent machine-check feedback. It re-verifies observations before
any external write and rejects missing, invalid, altered or duplicate runs. It never reruns
the model or providers. Dataset examples carry case IDs/manifest/verifier identity; experiment
metadata carries source/base/model/evidence identity. An existing dataset must match the
frozen references exactly. Root trace latency measures the recorded-result lookup/upload;
use `outputs.metrics` for actual workflow latency, tool counts and usage. This distinction
prevents a fast upload from masquerading as fast agent execution.

Evidence labels are separate: `scripted-controlled` exercises deterministic graph behavior;
`real-model-replay` adds actual configured-model reasoning over controlled providers;
`live-provider`, `reference` and `simulator` are distinct evidence layers and are not produced
by this runner. LangSmith uploads do not turn one layer into another. Use
`scripts/review_traces.py` for objective operational trace review and separately authorized
human review; its owner rubric is not populated automatically by this suite.
