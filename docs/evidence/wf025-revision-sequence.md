# WF-025 revision sequence correction

Observed November 12, 2026 UTC. This correction shipped in [v0.4.6](v046-release.md) through
[PR #24](https://github.com/IntelIP/InfiniteFlightAgent/pull/24). The original fix was committed as
`c5deeee3aa8ba2582cf67926f91568cc4ca93510` on `codex/wf025-revision-sequence`, based on
`b2e4fbf9f815da1c716fd4d4618f69e6c7f58ed2`.
The following pre-release observations retain their original source/image identities. The
[original release observations](v045-evaluations.md) remain unchanged; the explicit WF-025-S1 supplement is not used to score this fix.

## Original scenario and cause

The unchanged WF-025 in `evals/workflow_cases_v044.json` requests the same KIAD–KEWR leg
twice: revision 1 with four passengers and revision 2 with five, with separate approvals,
both OFPs and briefings retained, and MCP restart recovery. Its original prompt does not
explicitly order two generations. The zero-clarification bound is unchanged.

Earlier traces show the agent interpreting these entries as alternatives or forgetting the
second requested revision after inspecting saved work. A fresh v0.4.5 replay reproduced a
second failure mode: it approved and prepared revision 2, then stopped without generating
or finalizing it. Both approvals were correct, but only revision 1 had a snapshot/briefing.

The correction is confined to `instructions.md`: explicitly numbered requested revisions
are processed in order unless presented as alternatives; successful `revise_dispatch`, like
`dispatch_flight`, must be followed by generation and finalization of its returned revision.
Completion is checked against the full request, with optional calibration questions deferred
until the sequence finishes. Each revision retains its own approval; rejection, provider
failure and uncertain Generate outcomes still stop the sequence.

## Matched actual-model MCP replay

Both runs used GPT-6-Luna/low through the existing configured access, the original prompt,
identical fixtures, clock `2026-11-08T11:00:00Z`, harness and deterministic oracles. No
evaluation file, case, follow-up, approval script, budget or verifier was changed.

- Suite SHA-256: `417223bbf3635f844ec1afeee7434b602f36b9b1d17d8441b58ccaf2ae778e3b`.
- Case SHA-256: `17a8d6513aabcbf0bb4a1692da5e2ef21b4822bc191773d84c984d48a0edbc3d`.
- Harness SHA-256: `1c6439c0a59849477b0b49969b7612ca3b57ddee24602989ff5ff999602a6bf3`.
- Corrected instructions SHA-256: `5023dc1800980e37735d2176066f0c9743303d1933880fb59acbdd0305eca51d`.

| Observation | Released baseline | Corrected working tree |
| --- | ---: | ---: |
| Original WF-025 | Failed, valid | Passed, valid |
| Exact approvals | 2 | 2 |
| Generate clicks | 1 | 2, one per revision |
| Retained OFPs and briefings | 1 | 2 |
| Clarification turns | 0 | 0 |
| Extra continuation turns | 2 | 0 |
| Model calls | 12 | 10 |
| Measured elapsed seconds | 70.489 | 62.664 |
| Input / cached-input / output tokens | 108944 / 18944 / 1162 | 86054 / 17920 / 1619 |

Baseline failed `generation_bounds` and `retained_legs`. Candidate passes every applicable
check, including exact input identity and approval, immutable correlated snapshots, no
duplicate generation, saved MCP results and restart recovery. Revision 1's snapshot stayed
unchanged after revision 2 was generated. There were no tool/schema errors, unauthorized
generations or fixture misses. These are isolated observations, not statistical quality or
latency improvements.

LangSmith retains both recorded results on the original dataset:
[baseline failure](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/b0daccec-86bb-471c-a31d-6a726bf736e3/compare?selectedSessions=c9510067-a2db-4c50-a5f9-7c7e7e39670e)
and [corrected candidate](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/b0daccec-86bb-471c-a31d-6a726bf736e3/compare?selectedSessions=70d10cd6-5414-4833-a960-6ce8c64345c0).
Experiment root latency measures upload lookup; measured agent/tool timings are in
`outputs.metrics`. Upload did not rerun the model or flight providers.

## Focused live acceptance

Hudson then requested the live WF-025 acceptance check. A new bounded batch allowed at most
two sequential Browserbase sessions, each capped at the existing 180 seconds (360 seconds
total), and four necessary FlightAware requests. The previous v0.4.5 release allowance
remained closed; its unused runtime was not reused.

Temporary Worker `infinite-flight-dispatcher-wf025-acceptance`, version
`1fee13ed-a36e-472a-b046-09cc6811788e`, ran
`registry.cloudflare.com/22835e3d34b299ddb9289ba22c7d2535/ifd-wf025-acceptance@sha256:e1437e0cf741af37f7b87d87784563365346da38ea94abd1d427c76838ee8a34`.
An operator-authenticated Container SSH connection verified the running instruction hash
against the corrected working tree before any flight call. Health reported 0.4.5, database
connected and paid operations enabled. Public staging health returned 401. The new scheduled
bootstrap took approximately 13 minutes to propagate; this wait opened no browser.

Conversation `wf025-live-20261112T024742Z`, trip `WF-025-live-20261112T024742Z`, used the
original prompt structure and same-leg passenger change. Only the unique trip id and past
date were replaced: both revisions depart KIAD for KEWR on November 13, 2026 at 12:00 UTC,
using standard A20N, N320HD and KGS. No sequence explanation, clarification response,
continuation message, route correction or Generate retry was supplied.

Revision 1 was approved, generated and finalized before revision 2's separate approval.
Both saved OFPs and form readbacks contain the requested load: four passengers, then five.
Both routes are `JCOBY4 SWANN PHLBO4`, each with 17 navlog entries and a retained briefing.
Snapshot hashes are respectively
`2016df0924f7742ce6df8526b57aaec717885a612741d93ec9eb39ef324eb948` and
`191a10cf278865cbc0783a5ec53e667777df232ddcdac7aa96629cb94c49d62e`.
Revision 1's stored raw hash remained unchanged after revision 2 generated. The saved-trip
MCP response correctly identifies revision 2 as latest. There were exactly two successful
Generate tool calls and two finalizations, with no blocked steps or unauthorized generation.

| Browserbase session | Telemetry seconds | Queue wait seconds |
| --- | ---: | ---: |
| `4ff2ad71-e5a9-4961-bc1f-f15150ac32e4` | 42.569 | 0.094 |
| `7942732f-90c9-4054-9068-9d398b27c579` | 54.720 | 0.080 |

The sessions did not overlap, both completed with `keepAlive=false`, and post-run inventory
found zero active sessions. Total browser runtime was **97.289 seconds**; the two-session
batch is consumed. Two FlightAware airport requests cost $0.03 at list price; all other airport
lookups were cached. Project `a83b22af-002c-4edf-9fd8-7c214be04f95` reported 78 browser
minutes before the run and 80 afterward. Runtime, provider counters and invoice cost remain
distinct; Browserbase/model invoice or credit cost is unknown.

All three live LangSmith roots ended without errors, with approval, approval and briefing-ready
outcomes. The [final live turn](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/projects/p/1314924f-9909-482f-aeae-5d78ab59b99c/r/58fd542b-6b11-4368-a1f2-51cb8fe4532a)
retains provider events and tool outcomes. Live server restart was not exercised; restart
recovery above belongs to actual-model replay.

The temporary Worker/cron, container application, registry/local image, SSH tunnel/keys and
tail watcher were removed. Test snapshots/briefings and private evidence are retained.
Production remained at 100% on v0.4.5 Worker `c569ec9f-ca03-48ee-a0fe-6aab246ed23e`;
the code was uncommitted at acceptance time; its unchanged integration bytes are now bound
to the commit above. The correction had not been promoted at that acceptance time;
release evidence is linked above.

## Two-distinct-leg live acceptance

Hudson separately requested the remaining two-leg test on the candidate. This batch again
allowed two sequential 180-second Browserbase sessions and four necessary FlightAware
requests, retaining the existing admission, queue, cleanup and uncertain-Generate controls.

The rebuilt image matched the focused test's exact digest `sha256:e1437e0cf741af37f7b87d87784563365346da38ea94abd1d427c76838ee8a34`.
Temporary Worker version `689f5882-bc64-49cf-9ab5-eeaee9582942` served it. The running
instruction hash and local integration digest matched the earlier passing candidate before
the trip began. Authenticated container health passed; public staging health returned 401.
The scheduled bootstrap took approximately seven minutes without opening a browser.

Conversation/trip `wf025-two-leg-20261112T033410Z` used private standard A20N, N320HD,
four passengers and KGS, with automatic routes/runways and default fuel:

| Leg | Departure UTC, November 13, 2026 | Saved route | Navlog entries |
| --- | --- | --- | ---: |
| 1: KIAD–KEWR | 14:00 | `JCOBY4 SWANN PHLBO4` | 17 |
| 2: KEWR–KIAD | 18:00 | `PORTT4 PARKE HYPER9` | 19 |

Both exact dispatches were approved separately and generated/finalized once each. Both OFPs
contain four passengers and takeoff performance, with saved briefings. Leg 1's snapshot
`75b026d5113dae45464b50acf8ad4407c7c65f78e097e296a696eb40c495b586` remained unchanged
after leg 2 generated snapshot
`ddfd8d263a020f7d468be29d1ef312ef965a2b4a36014193cb2aaf4b1998b5f9`.
No clarification, continuation, route correction or Generate retry was supplied.

The operator client initially stopped before approval because its guard rejected the requested
"Standard A320neo airframe" description. Its recovery adapter also needed to handle
`conversation_status` omitting the action name. Both diagnostic stops occurred with zero
approvals and zero Generate calls. The corrected client verified the persisted inputs against
the original pending approval, then resumed that same conversation. Earlier diagnostic logs
remain retained; no new flight request or replacement browser was used to work around them.

The existing, unchanged `record_live_acceptance.legs/writes` and `acceptance.outcomes`
functions derived **all four BUILD-04 outcomes as passed** from the service database:
MCP generation, neo takeoff data, two distinct retained legs, and signed-in generation after
approval wait/resume. The private report records the working-tree source, image and Worker
version explicitly. Live process restart was not part of this test.

Browserbase sessions `04f0f050-da45-4c6e-9785-13bdb46edb49` and
`41d44942-7e4d-4131-8214-919b1a1d5655` ran sequentially for 42.668 and 62.786 telemetry
seconds: **105.454 seconds total**. Admission waits were 0.220/0.207 seconds. Both completed,
each below 180 seconds with `keepAlive=false`; zero browsers remained active. Two FlightAware
airport requests total $0.03 at list price; later airport reads were cached. The project
counter increased from 80 to 82 browser minutes. Invoice/credit costs remain unknown.

All three LangSmith roots ended without errors; the
[final turn](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/projects/p/1314924f-9909-482f-aeae-5d78ab59b99c/r/1ecc4238-bc60-4d2b-8c76-d0825b216384)
reported `briefing_ready`. The temporary Worker/cron, container application, registry/local
image, SSH tunnel/keys and tail watcher were removed. Production remained on the unchanged
v0.4.5 Worker `c569ec9f-ca03-48ee-a0fe-6aab246ed23e` at 100%.

## Checks and release boundary

Local validation passed **458 tests**, including all 28 controlled MCP scenarios and the
original eight regressions, with three Postgres-only skips. Ruff and dead-code checks passed.
All required BUILD-04 live outcomes pass for this unchanged candidate, in addition to the
focused revision test. The [original source-bound acceptance record](https://github.com/IntelIP/InfiniteFlightAgent/blob/ddd03f6cff915ad2f099441ed90287195e7b606d/docs/evidence/live-acceptance.json) now binds the
two-leg service records to `c5deeee3aa8ba2582cf67926f91568cc4ca93510` and Worker version
`689f5882-bc64-49cf-9ab5-eeaee9582942`, using the existing recorder without changing its
guard or oracle. Its integration digest is
`ed3bb00168147a1cb48d400c55ab58869752aab1860acab1dac6fecfe466e671`, identical to the
retained working-tree/image identity from both live tests. The commit was created after
those tests from the same integration bytes; this is a source binding, not a new deployment.
Recording it read the retained database rows and made no Browserbase or FlightAware calls.
No further live flight run was needed for those unchanged integration bytes. Subsequent
version preparation changed the integration fingerprint; the [v0.4.6 report](v046-release.md)
records the exact release-image acceptance and production promotion separately.

Replay used **zero Browserbase sessions and zero FlightAware requests**, isolated temporary
stores and no production plan writes. Its observations remain separate from the live test.
Model invoice/credit cost remains unknown, and queue/browser latency is unavailable in replay.
Raw runs, comparison, usage summaries, LangSmith receipts, database-derived live outcomes and
check/cleanup logs are retained at `artifacts/private/wf025-fix/`, including the `live/` and
`two-leg/` batches. Validation details are under `artifacts/validation/`.
