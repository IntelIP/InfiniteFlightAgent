# v0.5.0 and v0.5.1 releases: managed trip preparation

Observed November 13, 2026 UTC. v0.5.0 added durable trip progress (`trip_progress`, INT-416)
and safe cancellation with turn deadlines (`cancel_trip`, INT-417). It was deployed, failed
live acceptance, and was rolled back. v0.5.1 fixed the failure and passed production live
acceptance, including cancellation.

## v0.5.0 incident and rollback

- [Release run](https://github.com/IntelIP/InfiniteFlightAgent/actions/runs/43368857075) from
  `3519df0b5fea383ae85cf60456a63bebf7926370`; Worker `bcca9620-3e4d-42be-bb1e-44acf95cce3a`
  at 100%, image `sha256:8a5bc1cda0e9…`.
- Every SimBrief generation failed before the click (`provider_error_unknown`, Browserbase
  session `3a957516-edf9-4245-9618-f730fecb23ea`, 6.2 s). Container log at 05:05:30:
  `playwright/driver/node: error while loading shared libraries: libatomic.so.1`. Dependabot
  [#33](https://github.com/IntelIP/InfiniteFlightAgent/pull/33) moved playwright 1.64.1 →
  1.65.0, whose driver needs a library `python:3.12-slim` lacks. Unit tests mock the browser,
  so CI never started the driver.
- The same v0.5.0 trip showed `cancel_trip` withdrawing a pending approval correctly, with
  one defect: `turn_status` still returned the withdrawn `approval_required`.
- Production was rolled back to v0.4.7 (Worker `42d1aede-d6f5-4e0b-a226-32617cab2c9e`) with
  `wrangler versions deploy`. No v0.5.0 plan was generated.

## v0.5.1 fix and release identity

[PR #37](https://github.com/IntelIP/InfiniteFlightAgent/pull/37) pins `playwright==1.64.1`,
makes `turn_status` report `cancelled` after `cancel_trip` (regression test fails without
the fix), and adds the CI `image` job that starts the Playwright driver inside the built
container. Locally that check reproduced the v0.5.0 failure (`Connection closed while
reading from the driver`) and passed on the fix.

- PR squash merge and release source/tag: `238f05ceee4984261cffcbe9d48e92088c19fca6`.
- [Release workflow](https://github.com/IntelIP/InfiniteFlightAgent/actions/runs/43370679495): guard, source CI including `image`, upload, owner-authorized production approval, promotion, trigger deployment and GitHub release publication passed.
- Production Worker: `62bc3afe-fb1f-474f-b2de-765ac1fdfeb5`, at 100%.
- Immutable image: `sha256:50cb0c37d75184b4576e091d8aed362d03543c672f47ce4074edd9350ad656e2`.
- Rollback Worker: `42d1aede-d6f5-4e0b-a226-32617cab2c9e` (v0.4.7). Do not roll back to v0.5.0.
- Integration digest: `3c11a1be1cbc5c631098d42a7b6411396c9488c7c5cdda21ae51d62b40544a5c`.
- Local: 478 tests passed with three Postgres-only skips; Ruff check and format clean.

## Production live acceptance (v0.5.1)

Acceptance ran on the promoted production Worker through the remote MCP tools.

**Cancel before approval.** Conversation `trip-7928b5ad19`, trip `v051-cancel-a-20261113`
(KIAD–KTEB, A20N). `cancel_trip` returned `cancelled` (`outcome: stopped`) and withdrew the
pending approval. `trip_progress` showed the turn and approval `cancelled`; `turn_status`
returned `cancelled`; a later `approve_dispatch` was refused ("This approval was cancelled
and cannot be approved. Nothing was dispatched or generated."); `conversation_status`
returned `approval_cancelled`; nothing was saved for the trip.

**Three-leg trip with a cancelled final leg.** Conversation `trip-6543469f37`, trip
`v051-acceptance-20261113`: private standard A20N, N320HD, four passengers, KGS, automatic
routes and runways, November 14, 2026.

| Leg | Departure UTC | Result | Retained route | Browser seconds |
| --- | --- | --- | --- | ---: |
| 1: KIAD–KEWR | 14:00 | generated, briefing ready | `JCOBY4 SWANN PHLBO4` | 39.4 |
| 2: KEWR–KIAD | 18:00 | generated, briefing ready | `DCT PARKE HYPER9` | 37.8 |
| 3: KIAD–KBOS | 22:00 | approval cancelled, never generated | — | — |

With leg 3's approval pending, `trip_progress` showed legs 1 and 2 `briefing_ready` and the
approval history. `cancel_trip` then withdrew leg 3 (`withdrawn_revisions: []`); afterwards
`turn_status` returned `cancelled`, `conversation_status` `approval_cancelled`, and
`approve_dispatch` was refused. Legs 1 and 2 kept their briefings (snapshots `a43b02a6…`,
`268a6e51…`). No Generate was retried and no browser remained active. All four
[database-derived BUILD-04 outcomes](live-acceptance.json) pass and product validation
reports `passed`.

## Limitations

Cancellation while a browser session is open, and the 600-second turn deadline, were not
exercised live; both remain controlled-test evidence. Leg 2's SimBrief-chosen route has no
SID (`DCT PARKE HYPER9`). Both briefings flag their FLEX thrust estimate as `SUSPECT`
(reduction over the 25% FAA AC 25-13 limit); thrust remains a simulation-grade estimate.
