# Trace-driven dispatcher release — v0.4.0

Prepared November 6, 2026 (US Eastern; checks continue November 7 UTC). This is the
v0.4.0 release, combining the proposed patch fixes and workflow additions into
one minor release. It was deployed November 7 at 19:07 UTC; aircraft expansion remains unverified.

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
Deployment and production live acceptance are verified below.

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

## Production deployment — November 7, 2026

- Release PR: [#17](https://github.com/IntelIP/InfiniteFlightAgent/pull/17).
- Release commit: `72d54ecc3917184b1a2ac6c8a81ae1c82d754af8`.
- [Release workflow](https://github.com/IntelIP/InfiniteFlightAgent/actions/runs/42404297013):
  guard, Python checks, Worker checks, image upload and promotion all passed.
- Worker version `331a9196-14ec-4197-b273-119c6e8a8ff7`, tagged `v0.4.0`, promoted to **100%**.
- [GitHub Release v0.4.0](https://github.com/IntelIP/InfiniteFlightAgent/releases/tag/v0.4.0)
  published November 7 at 19:07:02 UTC and verified as Latest.
- The pre-publication validator passed 223 tests (3 skipped), lint and dead-code checks.
  Worker type checks and six Worker tests also passed.

## Production live acceptance — November 7, 2026

After the owner completed Access OAuth consent, the real production MCP service generated
and finalized `KDEN-KIAD-20261108`, thread `trip-2abc41c671`, on the released code above.
`record_live_acceptance.py` read production checkpoints, requests and snapshots and derived
**PASS** for all four required outcomes: MCP generation, neo takeoff performance, independent
retention of both legs, and authentication/approval/resumption. There were two approval pauses;
no fixture or local agent was substituted for production.

| Leg | Flight | Departure on November 8 | N1 ratio and range |
| --- | --- | --- | --- |
| 1 | UA1101 KDEN → KIAD | 07:40 MST / 14:40 UTC | 0.875 (0.834–0.923) × full-thrust N1 |
| 2 | UA1126 KIAD → KDEN | 14:10 EST / 19:10 UTC | 0.921 (0.877–0.956) × full-thrust N1 |

The second approval displayed a computed **1 h 14 min** connection. It also carried the
completed first leg's briefing. The Denver briefing printed both the suspect-reduction and
high-altitude warnings in code. Both briefings reported that plan checks passed while
simulator performance remains unverified. The return used a historical gate labeled with
its observation date. Saved-trip and conversation-status tools returned the retained plans
and saved conversation without another generation.

Provider measurements from completed turn responses total **$0.145 FlightAware list-price
usage** and **53.972 Browserbase session seconds**. This is not an invoice: credits/discounts,
Browserbase charges, model/ChatGPT-plan capacity and infrastructure charges are separate.
The production run's private response log remains in `artifacts/private/v040-production-mcp.json`.
Sanitized source-derived acceptance is in [live-acceptance.json](live-acceptance.json).

Production run ids include `76536795-7237-4e74-b1ca-e8fc12c5c368` (first generated leg and
return approval) and `48a32344-57da-47fc-a82a-2caad5126060` (final briefing). The MCP responses
included versioned run identity, objective workflow outcomes, FlightAware cache/page costs,
and released Browserbase session timing. A read-only LangSmith query confirmed `v0.4.0` tags,
`approval_required`/`briefing_ready` feedback and zero blocked steps on those actual runs.
These signals do not claim owner acceptance or simulator verification.

One conversational follow-up remains: before the first leg was dispatched, connection
checking had no saved prior-leg arrival, so the agent asked an extra confirmation. The
subsequent deterministic approval correctly checked the actual connection. This did not
prevent either leg, and is recorded for a future conversation-friction improvement.
