# PR #21 live acceptance

Observed November 10, 2026 UTC (November 9 in New York). Candidate:
`c8ef97b712a3824bfbafd41cfff57ddf0a6f04c6`. The integration source was unchanged
throughout this run. The [database-derived acceptance record](live-acceptance.json)
passes all four BUILD-04 outcomes: deployed MCP generation, real neo takeoff
performance, two retained legs, and approval wait/resume with signed-in generation.

## Deployment and transport

The exact candidate was built on the Windows/WSL Docker host and deployed to temporary
Worker `infinite-flight-dispatcher-pr21-acceptance`, version
`c87ae17e-ce80-444f-b464-6b45739d6250`, with its own Durable Object namespace and
container application. Registry image digest:
`sha256:1cfa43a66420be439d2c093b234e2062bcdffdf1d9975be0bf5b206aa3b1bea3`.

The scheduled bootstrap returned `skipped` without opening a browser. The public
staging health endpoint rejected unauthenticated access with HTTP 401. The Python
MCP client used Streamable HTTP through an operator-authenticated Container SSH
tunnel and retained internal-token authorization. The public Access OAuth journey
was not rerun. The candidate still reports package version 0.4.2; this is PR
acceptance, not a v0.4.3 release.

## Observed trip

Conversation: `pr21-acceptance-20261110T041609Z`.
Trip: `pr21-20261110T041609Z`. Both legs used standard A20N, callsign N320HD,
four passengers, KGS, automatic runways and default fuel. The client checked the
exact inputs and waited before consenting to each dispatch. No input correction
was needed; route arguments were null so SimBrief performed automatic routing.

| Leg | Departure UTC | Retained route | Navlog entries |
| --- | --- | --- | ---: |
| KIAD–KEWR | November 11, 14:00 | `JCOBY4 SWANN PHLBO4` | 17 |
| KEWR–KIAD | November 11, 18:00 | `PORTT4 PARKE HYPER9` | 21 |

Each leg has takeoff performance, a distinct immutable snapshot hash and a saved
briefing. Both remained available after the return leg replaced SimBrief's latest
plan. The route counts come from the retained raw OFPs; normalized performance
snapshots do not contain the route/navlog fields.

## Usage and limits

| Leg | Provider session lifetime | Admission timer | Final state |
| --- | ---: | ---: | --- |
| 1 | 67.665 seconds | 3.932 seconds | COMPLETED |
| 2 | 70.147 seconds | 3.581 seconds | COMPLETED |

Exactly two new sessions were observed, without overlap. Both used
`keepAlive=false` and dispatcher management metadata. The existing requested
180-second server lifetime and one-active-workflow policy were retained. Idle
cleanup and confirmed release appeared in both turns; no replacement browser was
created. No browser remained active afterward.

Browserbase project `a83b22af-002c-4edf-9fd8-7c214be04f95` reported 64 minutes
before and 66 afterward. Actual session runtime totaled 137.812 seconds; the whole
client journey took 322.432 seconds. Application telemetry recorded two uncached
FlightAware airport requests and a $0.03 list-price estimate. Provider counters,
runtime estimates and invoice charges remain distinct; Browserbase/model invoice
costs are unknown.

## Traces, evidence and cleanup

LangSmith recorded three successful root turns for this conversation, each with
zero automatic blocked-step feedback; the final turn reported `briefing_ready`.
The [final live turn](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/projects/p/1314924f-9909-482f-aeae-5d78ab59b99c/r/a829bf58-a8a4-48c2-bfdc-8f1092226010)
is an operational trace, separate from owner ratings and simulator acceptance.
Private MCP receipts, session metadata, routes, deployment records and trace IDs
are retained under Git-ignored `artifacts/private/pr21-acceptance/`.

The temporary Worker, cron trigger, container application, SSH tunnel, temporary
key and temporary secrets file were removed. Production remained at 100% on
v0.4.2 Worker version `42be74fa-87e9-4226-a3a5-debaec360173`, verified before and
after the run. Flight records and OFPs remain retained as acceptance evidence.
This run establishes neither simulator import nor aircraft thrust accuracy.
