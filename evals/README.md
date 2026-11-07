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


## Generation and recovery with controlled providers

```sh
uv run python evals/run_workflow_replay.py
```

This runs the real configured model and graph, approval pauses, workflow, parser, local
storage and briefing rendering. Provider responses are controlled: a pre-click mismatch,
a successful retry, an observed-reading calibration follow-up, and the Auckland range/fuel
failure. It uses ChatGPT-plan capacity and LangSmith tracing, with zero FlightAware requests
or Browserbase sessions. It does not prove live generation or simulator accuracy.

Research replay also isolates the saved-trip/revision tools from production storage and
blocks the new airframe browser tool, so adding a tool cannot silently bypass replay mode.
