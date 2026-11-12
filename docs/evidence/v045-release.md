# v0.4.5 release

Observed November 12, 2026 UTC (November 11 in New York).
[PR #23](https://github.com/IntelIP/InfiniteFlightAgent/pull/23) merged as
`f434f85bd63cfd92d0ab136668a91895d6ba4d9f`, the exact release source. Its tree matches
validated PR head `57e3a3466adccf5d3918fcff007917c267e64c46`. This release ships the
existing-profile engine/condition validation, calibration-unit scope and retained estimate
disclosures. It introduces no new aircraft support or numerical formula.

## Production, approval and rollback

Hudson explicitly authorized merging PR #23 and releasing v0.4.5. The
[Release workflow](https://github.com/IntelIP/InfiniteFlightAgent/actions/runs/43126314847)
passed exact-source Python/Worker CI and uploaded the candidate without traffic. The exact
uploaded image then passed the staged acceptance below and final local product validation.
The existing GitHub production environment was approved under that authorization, followed
by promotion, daily-trigger deployment and
[v0.4.5 publication](https://github.com/IntelIP/InfiniteFlightAgent/releases/tag/v0.4.5).

- Production Worker: `c569ec9f-ca03-48ee-a0fe-6aab246ed23e`, observed at **100% traffic**.
- Image: `registry.cloudflare.com/22835e3d34b299ddb9289ba22c7d2535/infinite-flight-dispatcher-dispatchercontainer-base@sha256:3554b740b1ac4cc28d635fc5dd91f80e9aa6db7e7de9461d12b81207dfe6fab8`.
- Tag and release target: `f434f85bd63cfd92d0ab136668a91895d6ba4d9f`.
- Production deployment recorded at 2026-11-12T00:48:15.973Z; release published at 00:48:21Z.
- A post-promotion unauthenticated production health request returned HTTP 401.

The authenticated **production** health request could not be rerun: Realm listed the existing
production pane as disconnected, and its host operations timed out. Opening the installed
Realm app did not reconnect that bridge. No credential or Access policy was changed to
work around it. The successful authenticated health and flight results below belong to the
exact image on staging, not to an authenticated production request. Deployment/routing and
public authentication rejection were observed; authenticated production runtime health
remains unverified in this release record.

Rollback: v0.4.4 Worker `74da7217-f7bf-45b0-b3b4-a0115c335b9d`, image
`sha256:3db056ca9cb6eba027332ea9caa3534fb91798d71fb8471d08d6bee9f779f657`, source
`eef57bcaec856b1bd56bc9b1a1a2f992b67fb61f`. The upload workflow recorded it at 100% before
promotion. The existing [rollback procedure](../implementation/deployment.md#rollback)
applies; no migration was added.

## Exact release-image acceptance

Temporary Worker `infinite-flight-dispatcher-v045-acceptance`, version
`6f26c860-207d-40a3-91b6-5c736d32ac1a`, ran the exact uploaded image above. Its new Cron
trigger required propagation before cold startup. The scheduled keep-alive returned 200
and skipped browser work. Public staging health returned 401; operator-authenticated
Container SSH with internal-token authorization exposed MCP for acceptance. Container
health reported `status=ok`, `version=0.4.5`, `database=true` and paid operations enabled.
An initial client connection before the tunnel was ready failed before any MCP/provider
request; health was checked successfully before the trip began.

Conversation `v045-acceptance-20261112T004026Z` prepared trip
`v045-20261112T004026Z`: two private standard A20N legs, N320HD, four passengers, KGS,
automatic runways/default fuel and omitted routes. The client checked exact dispatch inputs
and paused before approving each leg once. There was no route correction, repeated
settled-input clarification, extra continuation request or Generate retry.

| Leg | Departure UTC, November 13 | Retained route | Navlog entries | Browser telemetry seconds |
| --- | --- | --- | ---: | ---: |
| KIAD–KEWR | 14:00 | `JCOBY4 SWANN PHLBO4` | 17 | 47.137 |
| KEWR–KIAD | 18:00 | `PORTT4 PARKE HYPER9` | 19 | 63.535 |

Both routes match their saved form readback. Both OFPs have takeoff performance, distinct
immutable snapshot hashes and saved briefings after the latest plan changed. The
[database-derived record](live-acceptance.json) passes all four BUILD-04 outcomes, including
approval wait/resume and signed-in generation. Navlog counts are retained data, not proof
of navigation validity. Spawn remained an unverified FBO/GA-ramp recommendation.

[The final live LangSmith turn](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/projects/p/1314924f-9909-482f-aeae-5d78ab59b99c/r/cbed78b8-7ac2-4189-b5cb-3e637cd25872) reported `briefing_ready`. All three root turns completed without errors.

Both thrust briefings retain the simulation-grade estimate label, method, assumptions,
source anchors and **SUSPECT** warnings. No calibration reading or simulator observation was
invented. Neither a successful flight plan nor a pinned simulation-source calculation
establishes Infinite Flight thrust accuracy or usable aircraft support.

## Evaluations, usage and cleanup

Final local product validation passed: **458 tests**, Ruff and dead-code checks; three
Postgres-only tests were skipped. Hosted PR product/Python/Worker/dead-code checks and the
exact-source release CI passed. [Paired actual-model evidence](v045-evaluations.md) remains
separate: the original targeted pair passed 5/5 baseline and 4/5 candidate, with WF-025
failures retained, one targeted paired rerun and a separately frozen explicit ordered-revision
supplement. Its candidate passed. These observations do not establish statistical quality
or latency gains; the unchanged 28-case controlled suite passes on both applications.
The [compatibility assessment](../research/v045-thrust-compatibility.md) owns numerical
references and per-profile limitations.

The release batch used two sequential sessions totaling 110.672 seconds, with admission waits of 0.380/0.379 seconds and two FlightAware airport requests. It is separate from [PR acceptance](pr23-live-acceptance.md). Across both batches: **four sessions, 223.875 seconds (3.731 minutes), four FlightAware requests**, within the approved four-session/720-second/eight-request ceilings.

Every session completed under its configured 180-second lifetime, with `keepAlive=false`,
dispatcher ownership and no overlap. Idle cleanup ended the second session in each batch;
no replacement browser opened and the completed plans remained retained. One active
workflow, two waiters, the 30-second queue/idle controls and cleanup/fencing remain unchanged.
Post-promotion inventory found zero active sessions and exactly the four authorized sessions.
The four-session allowance is consumed; unused runtime does not authorize another session.

Project `a83b22af-002c-4edf-9fd8-7c214be04f95` reported 72 browser minutes before PR
acceptance, 74 after PR acceptance and 76 after release acceptance/post-promotion. These
counters differ from measured runtime and invoice cost. FlightAware telemetry totals $0.06
at list price; Browserbase/model invoice cost and remaining ChatGPT credit balance are
unknown. The configured model worked after Hudson raised Subscription Sharing from 10%
to 100%; no alternate model, API key, purchase or subscription was selected.

The temporary Workers/crons, container applications, PR registry/local image, SSH tunnels/keys,
tail watchers and secrets files were removed. The production release image and rollback
version are retained. Existing research/replay worktrees and unfinished work are preserved.
Private client/provider receipts, retained-plan summaries, LangSmith metadata, validation,
workflow artifacts and cleanup notes are under `artifacts/private/v045/`.

INT-415 covers this release. INT-412–414 remain open for independent per-profile references,
tolerances and current-build simulator engine/native PERF/N1 observations. Verified support
remains **0/51**. A fresh Access consent journey, intended-client journeys, simulator import
and numerical aircraft accuracy were not established. The disconnected Realm host also
prevented an authenticated production-health rerun, as distinguished above.
