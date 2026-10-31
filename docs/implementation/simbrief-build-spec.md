# SimBrief implementation contract

October 30, 2026. Authority: user-supplied implementation instructions in this conversation. Scope: DISC-03, DISC-06, BUILD-04; necessary SETUP-01, BUILD-01, and MCP/persistence portions of BUILD-02. No thrust resolver, flight-data provider, model provider, hosting, or publication selection.

## Outcome and acceptance

Prepare incomplete dispatch inputs through MCP, obtain the missing values, generate through the authorized provider integration, retrieve the correlated OFP, and preserve complete raw and normalized snapshots per trip/leg/revision. Required acceptance is an observed generation through MCP, an actual neo response, two retained legs after latest-plan changes, applicable authentication/waiting/resumption, and durable validation evidence. Passing local tests alone cannot close BUILD-04.

## Implementation boundaries

Hudson confirmed Python on October 30, 2026. Use a local stdio MCP server for development; remote client hosting remains undecided. The deterministic SimBrief tools do not require a model call. They are intended for the later Deep Agents coordinator, not a replacement for it.

Use the official MCP SDK, a validated input model, HTTP retrieval, and local durable persistence. Avoid an internal MCP subprocess and do not expose private raw account data indiscriminately through tool responses. Store snapshots in Git-ignored local data with restricted permissions. Return only the fields the operation needs; retain the original privately.

## Operations

- Prepare: validate explicit trip/leg/revision, origin, destination, exact provider aircraft/custom-airframe identity, UTC date/time, units, and supplied options. Return missing fields and visible provider defaults without submission. Reject invalid fields rather than silently dropping them. Generate the request fingerprint from canonical validated input.
- Retrieve: explicit user action only. Accept configured account identity and optional documented static identity. Use `client` and `json=v2`; no background latest-plan polling. Classify HTTP/network, embedded provider, malformed response, and missing-plan errors.
- Save snapshot: retain exact response bytes and digest, retrieval time, observed provider identifiers, and normalized data transactionally. An existing revision cannot silently change; identical content may return the existing result. Retrieval errors must not overwrite a prior good snapshot.
- Read snapshot: local lookup by explicit trip/leg/revision; does not fetch latest or change another leg. Keep saved snapshots available across process restarts.
- Extract takeoff: select the runway by identifier, never array position. Preserve complete conditions and all runway results, strings, zero, empty arrays, units, messages, and engine identity. Missing targets remain unavailable; no numerical thrust method is included.
- Generation: implement only once the authorized generation contract is available. Persist request and operation identity before sending. Uncertain outcomes remain unknown until supported reconciliation or user action resolves them. No blind retry and no automatic use of a newer unrelated latest plan.

## Correlation

Do not treat a successful latest fetch as proof that a submitted operation succeeded. Match documented provider/static identity, aircraft, airports, generation time, and agreed inputs at the fields available. Mismatches return explicit evidence and do not complete the operation. Custom-airframe identity may require provider metadata beyond ICAO code. Preserve source units; do not infer kilograms from numeric magnitudes.

## Verification plan

Use the existing sanitized B38M observation for nested-array and missing-target regression, plus explicit synthetic malformed/zero/error/mismatch cases labeled as such. Exercise the MCP protocol with a real local client process, not only direct Python function calls. Verify persistence over restart and independent legs locally, then separately establish live two-leg provider behavior. Use a mocked transport only for failure injection; it cannot prove generation.

SETUP-01 must add pinned dead-code checks, product-validation manifest, and CI using the actual PR head SHA. Every validator invocation must produce durable passed/failed/blocked evidence. This repository currently has no commit, and commits are not authorized: local evidence must identify a working-tree digest honestly; exact-commit validation remains incomplete until a commit is authorized.

## Generation access finding

Live public documentation was inspected again October 30. The legacy generation bridge requires an issued API key and supplied integration files; its browser flow preserves SimBrief login. The newer API's endpoint documentation is delivered privately. The Alias retrieval contract does not confer generation permission.

Checked environment variable presence for SIMBRIEF_API_KEY, NAVIGRAPH_CLIENT_ID, NAVIGRAPH_CLIENT_SECRET: absent. Exact Keychain service-name metadata lookups for SimBrief, Navigraph, and InfiniteFlightDispatcher: no matching items. No project Doppler selector or Git remote exists. No secrets were read and no external account changed. These checks do not prove absence from every possible store; request an existing credential location/documentation before requesting replacement credentials.

Sources: [legacy integration](https://developers.navigraph.com/docs/simbrief/using-the-api), [login flow](https://developers.navigraph.com/docs/simbrief/how-it-works), [developer onboarding](https://developers.navigraph.com/docs/simbrief/introduction), [API v2 documentation delivery](https://forum.navigraph.com/t/api-v2-jwt-no-endpoint-documentation/23817).

## Prepared developer-access inquiry — not sent

We are developing a personal Infinite Flight dispatcher accessed through ChatGPT, Claude, or Codex via MCP. It will prepare user-agreed flight inputs, generate a SimBrief OFP, and retain leg-specific results. Could you provide the supported API v2 generation/retrieval documentation and personal-use eligibility, required client/scopes, authentication flow, request/completion/reconciliation semantics, static/plan identity behavior, and runway-analysis output schema? Please confirm whether this integration model is permitted and whether existing legacy access is necessary or superseded.

No contact is authorized or performed. Existing developer documentation/access, if available, should be reused before this inquiry is sent.

## Prepared parser fixture

The [selected OFP fixture](../research/evidence/simbrief-b38m-parser-fixture.json) preserves original parameter/aircraft/airport context, times, weights, and complete takeoff/landing analysis without account data. Its [provenance](../research/evidence/simbrief-b38m-parser-fixture-provenance.json) records original and extracted digests and intentional omissions. A direct check confirmed that the TLR subtree matches the original, including eight takeoff runway results and empty target arrays. This is parser input evidence, not a passing parser test or complete OFP schema.
