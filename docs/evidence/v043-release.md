# v0.4.3 release

Observed November 11, 2026 UTC (November 10 in New York).
[PR #21](https://github.com/IntelIP/InfiniteFlightAgent/pull/21) merged as
`7cecc73024b958a7a554edbea839208fa0cd3304`. Version preparation produced release
source `710513f5d6c868a90e1aa8041dbcf689c0c476c0`; only the package version,
corresponding lock entry and changelog changed after merge.

## Release and production observations

The owner authorized merge and production deployment. The existing
[Release workflow](https://github.com/IntelIP/InfiniteFlightAgent/actions/runs/42930216321)
passed CI and uploaded an immutable image without traffic. After staged acceptance
and final product validation passed, owner-authorized approval released the existing
GitHub production environment gate. Promotion, trigger deployment and
[v0.4.3 publication](https://github.com/IntelIP/InfiniteFlightAgent/releases/tag/v0.4.3)
all succeeded.

- Production Worker: `06401807-3277-4077-b921-dc98ca348e08`, observed at 100% traffic.
- Image: `registry.cloudflare.com/22835e3d34b299ddb9289ba22c7d2535/infinite-flight-dispatcher-dispatchercontainer-base@sha256:776b92ad22032475baa2d0f24da1e93c9811741c6830f4677511e93a1a3b6bd2`.
- Rollback Worker: `42be74fa-87e9-4226-a3a5-debaec360173` (v0.4.2).
- Published tag resolves to release source `710513f5d6c868a90e1aa8041dbcf689c0c476c0`.
- Unauthenticated production `/health` returned HTTP 401 after promotion.
- Browserbase inventory showed zero active sessions and no additional sessions from promotion.

These are deployment, release and access-denial observations. No production flight
generation or public Access OAuth client journey was rerun. The Worker restarts its
container on the next request when its image fingerprint changes; a production
runtime `/health` response was not observed in this release check.

## Exact-image live acceptance

Temporary staging Worker `infinite-flight-dispatcher-v043-acceptance`, version
`998ce270-c438-4710-84aa-e3cadc9503f5`, ran the exact uploaded release image.
The scheduled bootstrap returned `skipped` without a browser. Public staging health
returned HTTP 401; the MCP client used an operator-authenticated Container SSH
tunnel with internal-token verification. Authenticated container health reported 0.4.3.

Conversation `v043-acceptance-20261111T003834Z` prepared trip
`v043-20261111T003834Z`. Both legs used standard A20N, callsign N320HD, four
passengers, KGS, automatic runway/default fuel and automatic routing. The client
checked the exact inputs and paused before approving each dispatch once.

| Leg | Departure UTC | Retained route | Navlog entries | Browser runtime |
| --- | --- | --- | ---: | ---: |
| KIAD–KEWR | November 12, 14:00 | `JCOBY4 SWANN PHLBO4` | 17 | 47.910 seconds |
| KEWR–KIAD | November 12, 18:00 | `PORTT4 PARKE HYPER9` | 16 | 52.997 seconds |

Both immutable OFPs and saved briefings remained available after the latest plan
changed. Each included takeoff performance. The
[database-derived record](https://github.com/IntelIP/InfiniteFlightAgent/blob/f979e649f2f7cbd9f9b1181d2e5acceda920b59a/docs/evidence/live-acceptance.json) passes all four BUILD-04 outcomes
for the exact release integration digest, including approval wait/resume and
signed-in generation. No Generate retry was needed.

Exactly two Browserbase sessions completed without overlap, totaling 100.907
seconds. Both had `keepAlive=false` and dispatcher ownership metadata; the existing
180-second provider lifetime remained in force. No browser remained active.
Project `a83b22af-002c-4edf-9fd8-7c214be04f95` reported 66 minutes before and
68 afterward. Reported usage and session runtime are distinct; invoice cost is unknown.

## Evaluation and checks

The frozen eight-case workflow suite ran on the clean release source with controlled
providers and a scripted model: 8/8 passed versus 6/8 on the matched v0.4.2 baseline,
with zero invalid cases or regressions. It made no FlightAware requests or Browserbase
sessions. The exact-source
[LangSmith experiment](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/60864283-3b33-417b-8403-76031cdee901/compare?selectedSessions=9688a186-57a2-4e32-8718-4bbc2f19e9b2)
is labeled `v043-release-scripted-79f09146`. Earlier actual-model replay of the two
regression scenarios passed 2/2 against 0/2 on baseline; that evidence covers the
unchanged implementation from PR #21 and is distinct from this release-scripted run.

Hosted Python and Worker CI passed. Final local product validation passed with the
fresh live record: 305 tests passed, three Postgres-only tests skipped; Ruff and
dead-code checks passed. Failure injection remains controlled-provider evidence,
rather than deliberately exhausting live allowance or stranding browsers.

## Retention and limits

Temporary staging Worker, cron, container app, tunnel, SSH key and secrets file were
removed before promotion. Private provider/MCP receipts, routes, deployment metadata,
workflow reports and cleanup logs are retained under Git-ignored
`artifacts/private/v043-release/`; GitHub retains upload and promotion artifacts.
Flight records and snapshots remain retained as acceptance evidence.

This release establishes the exercised dispatch integration and the observed
production rollout. It does not establish simulator import, aircraft thrust accuracy,
all client journeys or statistically measured model latency. Verified aircraft
support remains zero; later release and aircraft work stays open in Linear.
