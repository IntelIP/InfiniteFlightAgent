# Trace-driven dispatcher release candidate

Prepared November 6, 2026 (US Eastern; checks continue November 7 UTC). This is the
local v0.4.0 candidate, combining the proposed patch fixes and workflow additions into
one minor release. It is not a production deployment or verified aircraft expansion.

## Implemented behavior

- Provider-default routes, explicit route/runway/load/airframe selection, final form readback,
  frontmost-dialog handling, retryable pre-click failures and an atomic Generate claim.
- Computed connection checks before recommendations; labeled field elevation.
- Fuel/range/weight assessment and provider messages. Infeasible flights withhold takeoff
  thrust-setting guidance. Aircraft configuration, simulator capacity and source remain explicit.
- Guided observed N1 readings, percentage targets and scoped reuse: same aircraft, engine,
  conditions, runway settings and simulator version, no older than seven days.
- Dated arrival planning using sourced block time and explicit timezones; generated arrival
  compared with the requested target. Ambiguous/nonexistent DST times require clarification.
- Saved trips, per-leg statuses, approved immutable revisions, revision differences, briefing
  refresh differences, and persisted conversation/approval inspection after a restart.
- Versioned remote traces, objective workflow feedback, provider-specific usage measurements,
  a reusable trace review command and a LangSmith conversation review queue.

## Findings that changed the implementation

The retained KLAX–NZAA standard A20N plan generated on November 6 reports ramp fuel
20,503 kg, maximum tank fuel 19,117 kg, takeoff fuel 20,273 kg versus a required minimum
31,642 kg, predicted landing fuel -7,101 kg, and `WARNING: FLIGHT EXCEEDS AIRCRAFT RANGE`.
The old briefing omitted all these failures. The candidate exposes them and does not
present the thrust setting as actionable. These are actual retained provider observations,
not an in-simulator range test.

The live form check exposed two additional causes: the departure-time confirmation resets
an explicitly selected runway, and an unknown `No Alternates Found` dialog can cover that
confirmation. Runway selection now happens afterwards, and unknown front dialogs stop for review.

## Evidence and remaining gates

- Required local validator: **222 tests passed, 3 skipped**, lint and dead-code checks passed. Tests include actual graph approval and SQLite checkpoint reconstruction.
- A subsequent real MCP HTTP client journey passed preparation/approval, generation and
  finalization, saved-trip retrieval and checkpoint recovery after loss of the in-memory turn.
  It also checked workflow-feedback dispatch and provider timing in the response. All **5 HTTP
  tests passed**. This check uses a scripted model and controlled provider responses; it does
  not duplicate the live-provider claim below.
- The changed persistence/workflow tests passed **55 tests** against a throwaway local Postgres cluster. The cluster was stopped after verification.
- Two real-model FlightAware replay cases passed, with zero paid provider requests and no
  fixture misses (`artifacts/evals/20261107T004725Z/summary.json`).
- Real-model workflow replay exercises pre-click retry, one Generate claim, finalization,
  subsequent calibration without regeneration, and infeasibility reaching the user.
  The provider responses in this run are controlled; they do not establish live generation.
- Actual SimBrief form readback for KIAD–KEWR, A20N airframe, four passengers, DCT and runway
  01R returned `filled`, after the departure-time prompt. Generate was not clicked.
- Actual KLAX–NZAA form check stopped for review on `No Alternates Found`, as required.
- `Infinite Flight release review` queue was created in LangSmith, with the Auckland,
  UA1855 and v0.3.1 Denver conversations. Four rubric fields distinguish task completion,
  unnecessary clarification, incorrect numbers and manual intervention. No owner ratings
  were invented. Queue id: `8ffa1749-0456-454f-a24d-93eac8e7bc46`.

- A real-model **live local two-leg trip** generated KIAD–KEWR and KEWR–KIAD through
  SimBrief, with two approval pauses, separate finalizations and retained legs. E2E-10 passed
  in 99.1 seconds. Measured FlightAware list-price usage was **$0.015** (one airport lookup);
  Browserbase session charges and ChatGPT-plan usage are separate and were not priced.
  Results: `artifacts/evals/e2e-20261107T005502Z/results.jsonl`.
  Browser sessions: [leg 1](https://www.browserbase.com/sessions/b92369d8-f709-4f76-8a6b-544bbeef90fa)
  and [leg 2](https://www.browserbase.com/sessions/9e264ec7-9e44-4f4d-81eb-a548d1f35e5b).
  This is live local-provider evidence during implementation, not a deployed MCP acceptance
  run or an in-simulator test. Final working-tree checks include the subsequent revision
  approval and error-reporting refinements.

Detailed local logs and browser session links are in Git-ignored `artifacts/private/`.
The required validator records its current working-tree digest and check results under
`artifacts/validation/`. Existing v0.3.1 production evidence does not validate this code.
Publication and production acceptance remain separate gates; no commit or deployment is
claimed by this document.

## Thrust investigation and aircraft expansion

No N1 model constants, tables, uncertainty ranges or warning thresholds changed. The
existing suspicion that Denver N1 is conservative is not established by SimBrief accepting
a FLEX temperature: the Auckland observation shows that SimBrief can generate an
infeasible OFP. Tuning the estimator merely to agree with such plans would be unjustified.
The candidate preserves suspect warnings and can collect an observed simulator N1 with
its exact conditions and version, enabling a later matched comparison.

The B772 GE90-94B plan in the recent UA1855 trace proves plan generation only. This repository
has no compatible B772 thrust resolver or observed Infinite Flight engine calibration.
A B772 numerical target therefore remains unavailable. The next aircraft-support step
requires the actual simulator variant/engine and an applicable independent target or
observed calibration; no cross-engine substitution or new support claim was made.

## Release gate

The required validator's local checks passed, but its overall result is **blocked**:
`Integration code changed since live acceptance on 49ebc8b; repeat it.` The previous production
acceptance is deliberately preserved. The next authorized shipping sequence is commit/push,
PR/code checks, merge/release, an exact-deployment live MCP two-leg run, and a separate
production-evidence PR. Until that is done, v0.3.1 remains production and this candidate
must not be called production-validated.
