# v0.4.6 WF-025 release

Observed November 12, 2026 UTC. [PR #24](https://github.com/IntelIP/InfiniteFlightAgent/pull/24)
is merged and [v0.4.6](https://github.com/IntelIP/InfiniteFlightAgent/releases/tag/v0.4.6)
is deployed at 100% through the existing production approval mechanism. Numbered revisions
now complete in order, and each approved `revise_dispatch` result is generated and finalized
before the agent reports it ready. Exact approval, retained earlier results and uncertain-Generate
stops remain required. The [fix report](wf025-revision-sequence.md) owns the unchanged original
WF-025 scenario, matched configured-model replay and earlier focused live revision evidence.

## Release identity and gates

- PR squash merge: `85b7f1f911c1830f1a55e4aba25abea381f4fbb7`.
- Release source/tag: `3c257da34faf637a4c8c70cb2e3799cb54e11347`.
- [Release workflow](https://github.com/IntelIP/InfiniteFlightAgent/actions/runs/43258004984): passed source CI, upload, owner-authorized production approval, promotion, trigger deployment and GitHub release publication.
- Production Worker: `2226a90f-baba-4123-9022-d1ac8e137890`, at 100%.
- Immutable image: `registry.cloudflare.com/22835e3d34b299ddb9289ba22c7d2535/infinite-flight-dispatcher-dispatchercontainer-base@sha256:c75bb04e64b4118caec27a623663da1e68c3e32871ddb79371de4a92c859455d`.
- Exact-image acceptance Worker: `3264d4eb-3eea-4260-adc2-1ec99fa97fc5`.
- Integration digest: `fb79ea2cd3da575fb310ca6ee8c5964dcd5d119addde6106fefd23cb4162bc6a`.
- Running instructions SHA-256: `5023dc1800980e37735d2176066f0c9743303d1933880fb59acbdd0305eca51d`.

The merged PR has identical integration bytes to the validated PR head. Release preparation
only changed version metadata and changelog. v0.4.5 was already tagged, so the patch is
v0.4.6. The first release CI run caught a missing changelog comparison link before image
upload or provider work; the link was fixed before the successful run. The version change
updates `uv.lock` and its integration fingerprint, requiring the new exact-image trip below.

Final product validation passed **458 tests**, with three Postgres-only skips, plus Ruff,
dead-code checks and all four database-derived BUILD-04 outcomes. The 28 controlled MCP
cases and original eight regression definitions remain unchanged. Existing matched actual-model
WF-025 replay is retained; no additional replay or quality/latency improvement claim is made.

## Exact-image live acceptance

Temporary Worker `infinite-flight-dispatcher-wf025-acceptance` ran the exact uploaded
release image before promotion. Container SSH verified the running instruction hash.
Authenticated container health reported `status=ok`, `version=0.4.6`, `database=true` and
`paid_operations_enabled=true`. Scheduled bootstrap took approximately six minutes; this
infrastructure wait opened no Browserbase session.

Conversation/trip `v046-acceptance-20261112T163555Z` used private standard A20N, N320HD,
four passengers, KGS, automatic routes/runways and default fuel:

| Leg | Departure UTC, November 13, 2026 | Retained route | Navlog entries |
| --- | --- | --- | ---: |
| 1: KIAD–KEWR | 14:00 | `JCOBY4 SWANN PHLBO4` | 17 |
| 2: KEWR–KIAD | 18:00 | `PORTT4 PARKE HYPER9` | 19 |

Both exact dispatches were approved separately and generated/finalized once each. Both raw
OFPs and form readbacks contain four passengers; both have takeoff performance and retained
briefings. Routes match their saved form readbacks. Leg 1's raw snapshot hash
`0f5ba22385abb04bb1c4a677946648ebaf98165a70b3fc5395b9e2237439f0bb`
remained unchanged after leg 2 generated snapshot
`93e37e0765072a8cb8c9b2b8592a56bd745a2b30592255f2b625c64661432366`.
The saved-trip MCP response returns both briefings. No clarification, continuation, input
correction or Generate retry was supplied. Navlog counts describe retained data, not proof
of navigation validity or simulator import.

The unchanged [database-derived acceptance record](live-acceptance.json) binds all four
passing BUILD-04 outcomes to the release source and exact-image acceptance Worker. Approval
wait/resume and signed-in SimBrief generation were exercised; live process restart was not.

All three live LangSmith roots ended without errors: two approval outcomes followed by a
reply whose workflow outcome was `briefing_ready`. The
[final turn](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/projects/p/1314924f-9909-482f-aeae-5d78ab59b99c/r/6643eda9-63bc-4f37-b6cd-603aa5fd46a0)
retains tool results and provider events. These live observations are separate from the
original same-leg revision replay and earlier live revision acceptance.

## Usage and cleanup

This release batch allowed at most two sequential 180-second Browserbase sessions and four
necessary FlightAware requests. Existing one-active-workflow, two-waiter, 30-second queue,
cleanup and fencing controls were retained.

| Browserbase session | Runtime telemetry seconds | Queue seconds |
| --- | ---: | ---: |
| `38128a0e-c107-4c00-862d-8a355eca7610` | 74.566 | 1.976 |
| `415b384b-5013-4194-b61f-22f8ba5f9dd0` | 76.514 | 1.966 |

The sessions did not overlap, both completed with `keepAlive=false`, and provider inventory
confirmed zero active browsers. Total telemetry runtime was **151.080 seconds**. The batch
is closed. Two FlightAware airport requests total **$0.03 at list price**; other airport
lookups were cached. Browserbase project `a83b22af-002c-4edf-9fd8-7c214be04f95` reported
82 browser minutes before and 84 afterward. Runtime telemetry, project counters and invoice
cost are distinct; Browserbase/model invoice or credit cost remains unknown. Earlier WF-025
batches and their separate closed allowances are recorded in the fix report.

Before production approval, the temporary Worker/cron, container application, SSH tunnel,
tail watcher, private keys and transient secrets file were removed. The production release
image is retained intentionally. Test snapshots/briefings and private logs remain under
`artifacts/private/wf025-fix/release/`; validator results are in `artifacts/validation/`.

## Production verification and rollback

Deployment metadata reports the tagged release Worker at 100%, and the release tag resolves
to the exact source above. Authenticated production health verification is pending completion
of the renewed Cloudflare Access Google sign-in in the existing Realm pane.

Rollback identity is the previous v0.4.5 Worker `c569ec9f-ca03-48ee-a0fe-6aab246ed23e`,
source `f434f85bd63cfd92d0ab136668a91895d6ba4d9f`, image
`sha256:3554b740b1ac4cc28d635fc5dd91f80e9aa6db7e7de9461d12b81207dfe6fab8`.
Use the existing release rollback procedure with that Worker version if needed; no rollback
was performed.

No new aircraft support, thrust formula, model/provider, subscription or operating limit
is introduced. Estimates retain their existing disclosures and SUSPECT warnings. Aircraft
accuracy, independent profile references, simulator import and a full intended-client OAuth
journey remain unverified; verified aircraft support is **0/51**. INT-412–414 and planned
v0.5 trip-control/configuration scope remain open.
