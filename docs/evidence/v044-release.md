# v0.4.4 release

Observed November 11, 2026 UTC (November 10 in New York).
[PR #22](https://github.com/IntelIP/InfiniteFlightAgent/pull/22) merged as
`eef57bcaec856b1bd56bc9b1a1a2f992b67fb61f`. That exact commit is the release source;
the version was prepared before merge. It completes INT-407–411.

## Production and rollback

The owner authorized implementation, merge and promotion through the existing workflow.
[Release run 42951639308](https://github.com/IntelIP/InfiniteFlightAgent/actions/runs/42951639308)
passed release CI and uploaded the immutable image without traffic. Exact-image staged
acceptance and final local product validation passed before the standard GitHub production
environment was approved. Promotion, daily-trigger deployment and
[v0.4.4 publication](https://github.com/IntelIP/InfiniteFlightAgent/releases/tag/v0.4.4) succeeded.

- Production Worker: `74da7217-f7bf-45b0-b3b4-a0115c335b9d`, observed at 100% traffic.
- Image: `registry.cloudflare.com/22835e3d34b299ddb9289ba22c7d2535/infinite-flight-dispatcher-dispatchercontainer-base@sha256:3db056ca9cb6eba027332ea9caa3534fb91798d71fb8471d08d6bee9f779f657`.
- Release tag resolves to `eef57bcaec856b1bd56bc9b1a1a2f992b67fb61f`.
- Authenticated production `/health?release=v0.4.4` returned `status=ok`, `version=0.4.4`, `database=true`, `paid_operations_enabled=true` through the existing signed-in browser and production Access/Worker path.
- Unauthenticated production health returned HTTP 401.
- Post-promotion Browserbase inventory showed zero active sessions and no sessions beyond the four authorized acceptance sessions.

Rollback identity: v0.4.3 Worker `06401807-3277-4077-b921-dc98ca348e08`, image
`sha256:776b92ad22032475baa2d0f24da1e93c9811741c6830f4677511e93a1a3b6bd2`, source
`710513f5d6c868a90e1aa8041dbcf689c0c476c0`. The existing
[rollback procedure](../implementation/deployment.md#rollback) applies; no migration was added.

## Exact release-image live acceptance

Temporary Worker `infinite-flight-dispatcher-v044-acceptance`, version
`cf1bf298-52e3-4968-944c-7fd89e888790`, ran the exact uploaded image. Its scheduled
startup skipped SimBrief refresh without a browser. Public staging health returned 401;
MCP used an operator-authenticated Container SSH tunnel with internal-token verification.
Authenticated container health reported 0.4.4. Cron propagation delayed startup, without
consuming browser allowance or changing production.

Conversation `v044-acceptance-20261111T033235Z` prepared trip
`v044-20261111T033235Z`. Both legs used standard A20N, callsign N320HD, four passengers,
KGS, automatic runways/default fuel and omitted routes for automatic routing. The client
checked exact inputs and paused before approving each leg once. No repeated settled-input
confirmation, route correction, extra go-ahead or Generate retry was needed.

| Leg | Departure UTC, November 13 | Retained route | Navlog entries | Browser runtime |
| --- | --- | --- | ---: | ---: |
| KIAD–KEWR | 14:00 | `JCOBY4 SWANN PHLBO4` | 17 | 46.960 seconds |
| KEWR–KIAD | 18:00 | `PORTT4 PARKE HYPER9` | 16 | 52.176 seconds |

Both routes match the saved form readback. Each leg has takeoff performance, its own
immutable OFP hash and a saved briefing after the latest plan changed. Navlog counts
are retained evidence, not a route-validity judgment. The
[database-derived record](live-acceptance.json) passes all four BUILD-04 outcomes for
this release integration, including approval wait/resume and signed-in generation.
The [final live LangSmith turn](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/projects/p/1314924f-9909-482f-aeae-5d78ab59b99c/r/b0e74fa7-1b3c-466e-8ac4-92debd2fcf35)
reported `briefing_ready`; all three live root turns completed without errors.

The release batch used two sequential sessions totaling 99.136 seconds, with admission
waits of 0.238 and 0.208 seconds, and two uncached FlightAware airport requests. It is
separate from [PR acceptance](pr22-live-acceptance.md), which used two sessions totaling
155.549 seconds and two FlightAware requests. Across both batches: **four sessions,
254.685 seconds (4.245 minutes), four FlightAware requests**, below the authorized
720-second runtime/eight-request ceilings. Every session completed under 180 seconds,
without overlap, with `keepAlive=false` and dispatcher ownership. Observed inventory
never exceeded one active browser. Existing two-waiter, 30-second queue/idle and cleanup/
fencing controls remain unchanged; failure/overflow scenarios use controlled services.

Project `a83b22af-002c-4edf-9fd8-7c214be04f95` reported 68 browser minutes initially,
70 after PR acceptance and 72 after release acceptance. These provider counters differ
from measured runtime and invoice charges. FlightAware telemetry totals $0.06 at list
price; Browserbase/model invoice costs remain unknown. No production flight was generated
for the post-promotion health check.

## Evaluation and capability

The [matched evaluation report](v044-evaluations.md) records all four LangSmith
experiments, fixture/clock/model/verifier identity and source-byte comparison. Controlled
MCP baseline/candidate passed 20/28 and 28/28; actual configured-model replay passed 17/28
and 28/28. The final sets have zero invalid cases, zero case regressions and zero tool/schema
errors. Replay made zero Browserbase or FlightAware calls. The original eight case
definitions are unchanged. Isolated pairs do not establish statistical quality or latency
gains; measured stage/turn latency and provider/model usage remain scenario-specific.

Final local product validation passed against the exact-image database record: 401 tests
passed, three Postgres-only tests skipped; Ruff and dead-code checks passed. Hosted PR
Python/Worker/dead-code/product checks and exact-source release CI passed. Required checks
establish the exercised outcomes, not simulator behavior or every possible provider option.

The [frozen v26 catalog](../research/aircraft-catalog-v26.md) contains 51 current aircraft,
11 separately retained legacy records and a strict-majority target of 26. Engine/rating,
displayed target, exact profile and native PERF/FMS gaps remain explicit. Published build
26.5.2/20344 is source research, not observation of the owner's simulator. Verified aircraft
support remains **0 of 51**. v0.4.5 thrust compatibility and v0.5 trip-control/configuration
work remain open in their existing scope.

## Cleanup and retained evidence

Both temporary Workers/crons, container applications, SSH tunnels/keys and secrets files
were removed; the temporary PR registry image, remote build tree and Docker credentials
were removed too. The production release image and v0.4.3 rollback identity are retained.
Private MCP receipts, saved-plan summaries, session metadata, LangSmith records, validation
logs and cleanup receipts are in Git-ignored `artifacts/private/v044/`; GitHub retains
upload/promotion artifacts. Isolated research/replay worktrees and pre-existing unfinished
work are preserved. Flight records, snapshots and evidence screenshots remain retained.

Production runtime health was observed through existing authentication. A fresh OAuth
consent journey, intended-client compatibility, simulator import and numerical thrust
accuracy were not established by this release.
