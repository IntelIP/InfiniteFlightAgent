# PR #22 live acceptance

Observed November 11, 2026 UTC. Application source:
`839d3647e086e60ee46ebca4b08ce62d8ff267b1`, unchanged through integration head
`e064d2fa9f793fade23742e7bab50e28fa0ebc58`. Temporary Worker
`infinite-flight-dispatcher-pr22-acceptance`, version
`d6bc7149-ab9a-41eb-ada0-9fb9d9ada0cd`, ran image
`sha256:a094cf16da42cb4e5e96e3170368829eacc30c1b6d62e1726732ec41f5ea26ad`.
Authenticated container health reported 0.4.4. Public staging health returned 401;
MCP used an operator-authenticated SSH tunnel with internal-token authorization.
The scheduled bootstrap skipped SimBrief refresh without opening a browser.

Conversation `pr22-acceptance-20261111T030518Z`, trip `pr22-20261111T030518Z`,
prepared two private A20N legs for November 13, 2026, using standard profile, callsign
N320HD, four passengers, KGS, automatic runway/default fuel and automatic routing.
The client checked all exact dispatch inputs and paused before approving each leg once.
No settled-input clarification, route correction, extra go-ahead or Generate retry was needed.

| Leg | Departure UTC | Retained OFP route | Navlog entries | Browser runtime |
| --- | --- | --- | ---: | ---: |
| KIAD–KEWR | 14:00 | `JCOBY4 SWANN PHLBO4` | 17 | 76.815 seconds |
| KEWR–KIAD | 18:00 | `PORTT4 PARKE HYPER9` | 16 | 78.734 seconds |

Both retained raw OFP routes match the recorded form readback. Distinct immutable
snapshots and saved briefings remain available after the latest plan changed; both have
takeoff performance. Navlog counts describe retained evidence, not navigation validity.
The [database-derived acceptance record](https://github.com/IntelIP/InfiniteFlightAgent/blob/da5980f6000e5b80e5abd67e765fe688c74a12f7/docs/evidence/live-acceptance.json) passes all BUILD-04
outcomes, including signed-in generation following approval wait/resume.

Exactly two sessions completed without overlap, totaling 155.549 seconds. Each used
`keepAlive=false`, dispatcher ownership and the existing 180-second provider lifetime.
Admission waits were 5.066 and 5.161 seconds; observed inventory never exceeded one
active browser. Two waiters, 30-second queue/idle limits and existing cleanup/fencing
remain configured. No browser remained active. Project usage increased from 68 to 70
minutes; this counter differs from runtime and invoice cost remains unknown. Two uncached
FlightAware airport requests carried a $0.03 list-price estimate. No additional provider
calls were made by the paired [workflow evaluations](v044-evaluations.md).

LangSmith retained three root turns. The
[final live turn](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/projects/p/1314924f-9909-482f-aeae-5d78ab59b99c/r/176fd77e-19d6-4a78-8cac-d3b186d50621)
reported `briefing_ready`; this is operational evidence, not owner/simulator acceptance.
Local product validation passed: 401 tests passed, three Postgres-only tests skipped,
Ruff and dead-code checks passed. Controlled failure/recovery scenarios and actual-model
replay are recorded separately from this live sample.

The temporary Worker/cron, container application, registry image, SSH tunnel/key, build
tree and temporary Docker credentials were removed. Private MCP/provider receipts,
retained-plan summaries, source identities, LangSmith metadata and cleanup logs remain
under Git-ignored `artifacts/private/v044/`. Production remained on v0.4.3 during this run.
Two of the four authorized sessions and two of eight FlightAware requests were used;
the remaining sessions are reserved for exact release-image acceptance. No simulator
import or aircraft thrust accuracy is established; verified aircraft support remains zero.
