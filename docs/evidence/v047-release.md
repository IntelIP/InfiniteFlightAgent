# v0.4.7 Route Finder release

Observed November 13, 2026 UTC (November 12 in New York). [PR #27](https://github.com/IntelIP/InfiniteFlightAgent/pull/27)
is merged and [v0.4.7](https://github.com/IntelIP/InfiniteFlightAgent/releases/tag/v0.4.7)
is deployed at 100%. With no agreed route, SimBrief generation fills the form and clicks
Generate Flight directly, keeping SimBrief's own route suggestion; Route Finder is never
clicked. Route verification ignores the explicit `DCT` tokens the OFP writes between fixes.
The README refresh ([PR #25](https://github.com/IntelIP/InfiniteFlightAgent/pull/25)) ships
in the same release.

## Incident

Trip `KEWR-EIDW-20261112` (private B752, no route) failed twice on v0.4.6 (2026-11-13
03:48 and 03:51 UTC) with `generate_in_simbrief` → `TimeoutError`, `clicked=false`.
Browserbase network logs for sessions `6c4ccc33-3807-4035-8b74-50c3964ff7d5` and
`e386b26c-b5f8-4f4d-9ad4-d3cde006d19b` show the form filled correctly, then the Route Finder
request to `api.simbrief.com/v2/routes/generate` received no response before the 30-second
`jQuery.active` wait expired, so Generate Flight was never reached. The agent called the tool
as instructed; the instructions were not the cause.

## Release identity and gates

- PR squash merge and release source/tag: `553a41ff8ceee658779196f2856b4cebc3ae241f`.
- [Release workflow](https://github.com/IntelIP/InfiniteFlightAgent/actions/runs/43365552719): passed guard, source CI, upload, owner-authorized production approval, promotion, trigger deployment and GitHub release publication.
- Production Worker: `42d1aede-d6f5-4e0b-a226-32617cab2c9e`, at 100%.
- Immutable image: `sha256:0ec30d9ff5256ea8a3dc737ac3d9e86c0b4ce2853f7593f1cf5d83972cef2389`.
- Rollback Worker: `2226a90f-baba-4123-9022-d1ac8e137890` (v0.4.6).
- Integration digest: `3f5c27cd714b6f1ba0c85c7056419c4e6b62ee8481cc12be0b17cd8441e33845`.
- Instructions SHA-256 (unchanged from v0.4.6): `5023dc1800980e37735d2176066f0c9743303d1933880fb59acbdd0305eca51d`.

## Local verification before merge

- Live browser check of KEWR–EIDW (B752, no route): `generated` in 35 seconds with route
  `MERIT HFD PUT BOS TUSKY FORTE NICSO NATS BEXET OLAPO OLAP4L`.
- Local end-to-end agent run of the same leg first exposed the `DCT` token readback mismatch
  (`plan_mismatch`); after the fix it completed with a briefing in 82 seconds.
- 449 tests passed with three Postgres-only skips; Ruff check and format clean.

## Production live acceptance

Unlike v0.4.6, acceptance ran on the promoted production Worker rather than a temporary
exact-image Worker before promotion. The first `plan_flight` call timed out client-side while
the new container cold-started (startup completed 04:32:05 UTC); no trip was saved and the
retry succeeded.

Conversation `trip-a674affc1b`, trip `v047-acceptance-20261113T0435Z`: private standard A21N,
N321HD, four passengers, KGS, automatic routes and runways.

| Leg | Departure UTC, November 13, 2026 | Retained route | Browser seconds |
| --- | --- | --- | ---: |
| 1: KIAD–KEWR | 14:00 | `JCOBY4 SWANN PHLBO4` | 36.8 |
| 2: KEWR–EIDW | 23:15 | `DCT MERIT DCT HFD DCT PUT DCT BOS DCT TUSKY DCT FORTE DCT NICSO NATS BEXET DCT OLAPO OLAP4L` | 58.7 |

Each leg was approved separately and generated/finalized once, with takeoff performance and a
retained briefing; leg 2's SimBrief message is `ETOPS FUEL REQUIRED`. Both browser sessions
were released. All four [database-derived BUILD-04 outcomes](live-acceptance.json) pass, and
product validation reports `passed`.

## Limitations

Removing the pre-Generate DCT stop means a short leg can retain a SimBrief-chosen direct
route; the briefing shows the retained route. Route counts do not establish navigation
validity or simulator import. Thrust remains a simulation-grade estimate.
