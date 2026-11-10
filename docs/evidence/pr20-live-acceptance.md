# PR #20 live acceptance

Observed November 10, 2026 UTC (November 9 in New York). Candidate:
`9363cd109eb88365753d68fa475643b74b7447de`. The integration source was unchanged throughout
the run. The [database-derived acceptance record](live-acceptance.json) passes all four
BUILD-04 outcomes: generation through deployed MCP, real neo takeoff performance, two
retained legs after the latest-plan change, and approval wait/resume with signed-in generation.

## Deployment and transport

The candidate ran on the temporary Cloudflare Worker
`infinite-flight-dispatcher-pr20-acceptance`, version
`c508ef1f-f47f-4031-9ad3-2ceedc7757f2`, with its own Durable Object namespace and container app.
Registry image digest: `sha256:0ed748ac3d0c84555a1fa960c802b963a8d4355e681bc65bd333cce15fec9f5e`.
The installed preview API does not support the project's Durable Object-managed container
mode, so a separate staging Worker was used. Its scheduled no-op keepalive bootstrapped the
container; the observed response was `skipped`, with login refreshed on demand.

The Python MCP SDK used Streamable HTTP through an operator-authenticated Cloudflare
Container SSH tunnel, retaining the service's internal-token authorization. The public staging
endpoint rejected unauthenticated access with HTTP 401. The public Cloudflare Access OAuth
client flow was not rerun. Production stayed on Worker version
`758f18dd-4c55-4df1-9017-8939e9eeddb1` at 100% traffic; these controls were not promoted.

## Observed workflow

Conversation: `pr20-acceptance-20261110T001841Z`. Trip: `pr20-20261110T001841Z`.
Both legs used the standard A20N, four passengers and KGS. The client waited before each
dispatch approval and checked the exact itinerary before consenting. Each approved leg was
generated once, finalized and saved before the next leg proceeded.

| Leg | Departure UTC | Route | Navlog entries |
| --- | --- | --- | ---: |
| 1, KIAD–KEWR | November 10, 14:00 | `JCOBY4 SWANN PHLBO4` | 17 |
| 2, KEWR–KIAD | November 10, 18:00 | `PORTT4 PARKE HYPER9` | 17 |

Both OFPs have takeoff performance and distinct immutable snapshot hashes. Both briefings
remained available after the second plan replaced SimBrief's latest-plan response. Automatic
routing produced named departure/arrival routing rather than direct-only routes.

One clarification was needed before generation: the agent initially put the literal words
`Route Finder` in the route argument. That dispatch was rejected before opening a browser.
The client clarified that the argument must be omitted; the subsequent approvals used null
routes and exercised automatic route finding. This remains an observed conversation-quality
limitation, not a claim that the first request was interpreted perfectly.

## Browser usage and management

| Session | Actual provider lifetime | Requested server lifetime | Final state |
| --- | ---: | ---: | --- |
| Leg 1 | 63.350 seconds | 180 seconds | COMPLETED |
| Leg 2 | 69.623 seconds | 180 seconds | COMPLETED |

Exactly two new sessions were recorded, with no overlap. Both had `keepAlive=false` and the
dispatcher management metadata. Session completion was confirmed before account ownership
was released. No browser remained active at the end. Reported project usage increased from
60 to 62 browser minutes; actual elapsed runtime totaled 132.973 seconds. Provider rounding
and invoice cost are separate from these observations.

Live inspection showed one active workflow and no waiters during generation, and idle
admission with no active browser after completion. Queue overflow, idle/deadline termination,
late create responses and ambiguous release fencing are covered by controlled-provider
tests; this run did not deliberately strand or time out a real browser.

## Evidence and cleanup

The recorder read the deployed service's checkpoint writes, generation metadata and retained
snapshots from the shared database. It derived all four passing outcomes without changing
validation requirements. Private MCP receipts, deployment logs, route summaries and provider
session metadata are under Git-ignored `artifacts/private/pr20-acceptance/`; no credentials or
connection URLs are published here.

The temporary staging Worker, schedule, container app, SSH tunnel and temporary SSH key were
removed after the run. Flight records and OFPs remain retained for acceptance evidence.
