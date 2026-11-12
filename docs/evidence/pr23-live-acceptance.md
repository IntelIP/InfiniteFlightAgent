# PR #23 live acceptance

Observed November 11, 2026 UTC. Application source is unchanged from
`170c4f1415613d8504c4f60d0937644847fcdd58` through deployed integration head
`bbc04f0ee6063bf8c29475f69b9e752cfae57a3b`. Isolated Worker
`infinite-flight-dispatcher-pr23-acceptance`, version
`bc9a26fd-66b8-40af-ae4c-ee45fe47ad8c`, ran image
`registry.cloudflare.com/22835e3d34b299ddb9289ba22c7d2535/ifd-v045-pr@sha256:b6cb75fafbdbdd7fb54103d9bde1118ec3c5bf75a1f5e6da716b540de6398875`.
Authenticated container health reported 0.4.5, database access and paid operations enabled.
Public staging health returned 401. MCP used an operator-authenticated Container SSH tunnel
with internal-token authorization. The new cron's propagation delayed cold startup without
opening a browser; its internal keep-alive returned 200 and skipped browser work.

## Trip and retained evidence

Conversation `pr23-acceptance-20261111T235110Z`, trip `pr23-20261111T235110Z`, prepared
two private A20N legs for November 13, 2026. Both used the standard profile, callsign
N320HD, four passengers, KGS, automatic runways/default fuel and omitted routes. The client
checked the exact dispatch inputs and paused before approving each leg once. No settled-input
clarification, route correction, extra continuation request or Generate retry was needed.

| Leg | Departure UTC | Retained route | Navlog entries | Browser telemetry seconds |
| --- | --- | --- | ---: | ---: |
| KIAD–KEWR | 14:00 | `JCOBY4 SWANN PHLBO4` | 17 | 48.724 |
| KEWR–KIAD | 18:00 | `PORTT4 PARKE HYPER9` | 19 | 64.479 |

Each route matches the saved form readback. Both legs have takeoff performance, distinct
immutable snapshots and saved briefings after the latest SimBrief plan changed. The
[database-derived acceptance record](live-acceptance.json) passes all four BUILD-04 outcomes,
including approval wait/resume and signed-in generation. Navlog counts describe retained
data, not navigation validity. Spawn remained an unverified FBO/GA-ramp recommendation.

Both retained thrust briefings label their output as a simulation-grade estimate and flag
the reduction as **SUSPECT**. They retain the method, assumptions and source anchors.
Those warnings remain material: integration success does not verify the estimate, simulator
engine identity, native PERF behavior or a usable aircraft-specific N1. No calibration
reading was invented. Verified aircraft support remains **0/51**.

Three LangSmith root turns completed without errors. The
[final live turn](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/projects/p/1314924f-9909-482f-aeae-5d78ab59b99c/r/03029388-23ad-44fe-a9c6-ebad9066294c)
reported `briefing_ready`. The [separate paired replay report](v045-evaluations.md) retains
both passing and failed actual-model observations; this live trip does not erase WF-025's
conversation/evaluation limitation.

## Bounded usage

Exactly two Browserbase sessions completed without overlap. Telemetry totals **113.203
seconds**; provider start/end timestamps total 113.052 seconds. Each session stayed below
the configured 180-second lifetime, used `keepAlive=false` and dispatcher ownership, and
was confirmed released. Admission waits were 0.359 and 0.376 seconds. The second session
recorded `browser_idle_timeout` cleanup; the completed plan remained retained and no
replacement session opened. This is an observed cleanup event, not a third browser.
Post-run inventory reported zero active browsers and exactly these two new sessions.

Project `a83b22af-002c-4edf-9fd8-7c214be04f95` reported 72 browser minutes before and 74
after. Provider minutes, measured runtime and invoice cost are different quantities; the
invoice cost is unknown. Two uncached FlightAware airport requests carried a $0.03
list-price estimate. Replay made zero Browserbase/FlightAware requests. The existing model
route worked after the owner increased Subscription Sharing from 10% to 100%; a remaining
credit balance or actual credit charge was not measured.

The fresh allowance covers PR and release acceptance together: four sequential sessions,
each capped at 180 seconds, and eight necessary FlightAware requests. **Two sessions and
six requests remain**, reserved for release acceptance; the session count bounds remaining
runtime to at most 360 seconds. One active workflow, two waiters, the 30-second queue/idle
limits and existing cleanup/fencing behavior remain unchanged.

## Cleanup and release state

The temporary Worker/cron, container application, registry image, SSH tunnel/key, tail
watcher and temporary secrets file were removed. Private client/provider receipts, retained
plan summaries, LangSmith metadata and cleanup records remain under
`artifacts/private/v045/resumed-acceptance/`. Existing research/replay worktrees and flight
records are preserved. Production was not changed and remains on v0.4.4.

This is PR-candidate staging acceptance. The exact release image, production approval,
promotion and production verification remain required. A fresh Access OAuth journey,
intended-client journeys, simulator import and numerical aircraft accuracy were not tested.
