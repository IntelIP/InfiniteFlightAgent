# SimBrief MCP extension investigation

Research date: October 30, 2026. Scope: DISC-03, with inputs to DISC-02. Public source/document inspection only; no installation, execution of upstream code, authenticated API calls, account changes, or messages.

## Question and decision informed

What can the existing server do, what must be extended, and which generation integration should we build? Decide the reuse boundary before implementation.

## Conclusion

Reuse the small retrieval foundation as an internal SimBrief adapter, preserving MIT attribution. Extend our dispatcher service around it rather than making the upstream text tools the application data model. Resolve authorized API v2 access/documentation before committing to the older generation bridge. Reading a plan is verified in source; generating or retaining real plans has not been demonstrated here.

## Confirmed facts: pinned source

Inspected upstream commit **`9813e8e88f93373b2e568bc8fb24cdaec40c92ca`** from GitHub's public commit/tree APIs. The following are source findings, not runtime results.

| Surface | Observed behavior | Evidence |
| --- | --- | --- |
| Runtime | Python >=3.11, `httpx>=0.28.1`, `mcp>=1.27.0`; development pytest/ruff | [pyproject.toml](https://github.com/Emanuele94/SimBrief-MCPServer/blob/9813e8e88f93373b2e568bc8fb24cdaec40c92ca/pyproject.toml) |
| License | MIT; retain copyright/permission notice when incorporating code | [LICENSE](https://github.com/Emanuele94/SimBrief-MCPServer/blob/9813e8e88f93373b2e568bc8fb24cdaec40c92ca/LICENSE) |
| Account binding | Pilot ID required at module import through an environment variable | [server.py L11–20](https://github.com/Emanuele94/SimBrief-MCPServer/blob/9813e8e88f93373b2e568bc8fb24cdaec40c92ca/server.py#L11-L20) |
| Retrieval | `_fetch` calls `xml.fetcher.php` with `userid`, `json=1`, optional `id`, 30-second timeout; checks HTTP and embedded error status | [L71–83](https://github.com/Emanuele94/SimBrief-MCPServer/blob/9813e8e88f93373b2e568bc8fb24cdaec40c92ca/server.py#L71-L83) |
| Tool surface | 14 retrieval tools; no dispatch generation, external flight research, saved trip state, or thrust resolver in this source | [server.py](https://github.com/Emanuele94/SimBrief-MCPServer/blob/9813e8e88f93373b2e568bc8fb24cdaec40c92ca/server.py) |
| Snapshot consistency | Tools call `_fetch` independently; the caller can therefore read different latest plans between calls | Same source; consistency risk is an inference from call behavior |
| Performance extraction | `get_performance` emits only truthy scalar children of `tlr.takeoff` and `tlr.landing`; nested dictionaries/lists and zero-valued entries are skipped | [L421–450](https://github.com/Emanuele94/SimBrief-MCPServer/blob/9813e8e88f93373b2e568bc8fb24cdaec40c92ca/server.py#L421-L450) |
| Full result | `get_full_flight_plan` deletes `navlog`, `notams`, and the entire `alternate` section before serializing | [L529–540](https://github.com/Emanuele94/SimBrief-MCPServer/blob/9813e8e88f93373b2e568bc8fb24cdaec40c92ca/server.py#L529-L540) |
| Units | Some text outputs hardcode kg; helper treats scalar zero as missing. Validate against source units before reuse | [L40–44](https://github.com/Emanuele94/SimBrief-MCPServer/blob/9813e8e88f93373b2e568bc8fb24cdaec40c92ca/server.py#L40-L44), [L105–120](https://github.com/Emanuele94/SimBrief-MCPServer/blob/9813e8e88f93373b2e568bc8fb24cdaec40c92ca/server.py#L105-L120) |
| Tests | Tool tests replace `_fetch`; the performance fixture is a small hand-built scalar dictionary, not evidence of the live schema | [tests L404–420](https://github.com/Emanuele94/SimBrief-MCPServer/blob/9813e8e88f93373b2e568bc8fb24cdaec40c92ca/tests/test_tools.py#L404-L420) |
| Existing CI | Ruff format/lint and pytest; no product or live-integration proof | [CI](https://github.com/Emanuele94/SimBrief-MCPServer/blob/9813e8e88f93373b2e568bc8fb24cdaec40c92ca/.github/workflows/ci.yml) |

Source SHA-256 values observed during retrieval:

```text
server.py       8e06bd15c79e59b5616f31f9d510b9d2f9163fc34e66a2d18ce1a77ab50c78c2
pyproject.toml  a257592745f8450626f017a79bfba0db76307c7631800f1151c3bd05eb2a29f9
LICENSE         33693b75c116a3677074d445edc5d1ce46a31d73ddbf78f0e472c59d7cd0feed
```

## Confirmed facts: official integration documentation

- The published legacy generation interface accepts `orig`, `dest`, and `type` as minimum inputs. It supports schedule, payload, runway, callsign, remarks, custom-airframe identity, `tlr=1`, and `static_id`. The latter retrieves the evolving flight even after other dispatches; preserve local revisions as well. The documented `acdata` weights use thousands of pounds except `paxwgt`. No dedicated gate field appears in the published table. [Using the API](https://developers.navigraph.com/docs/simbrief/using-the-api).
- The legacy process uses a logged-in user and popup generation. It does not bypass login. [How it works](https://developers.navigraph.com/docs/simbrief/how-it-works).
- Latest OFP retrieval supports Pilot ID or username and JSON output. [Fetching OFP data](https://developers.navigraph.com/docs/simbrief/fetching-ofp-data).
- Public 2026 API v2 discussions show endpoint documentation delivered privately after credentials. Users report JWT/device-flow use; staff respond through email/DM. These threads establish a newer access path, not its complete protocol or our entitlement. [July thread](https://forum.navigraph.com/t/api-v2-jwt-no-endpoint-documentation/23817), [August thread](https://forum.navigraph.com/t/simbrief-api-v2-endpoint-documentation-never-arrived-ticket-37604/24168). Staff direct applicants to the developer team for SimBrief endpoint guidance in the [REST API discussion](https://forum.navigraph.com/t/simbrief-rest-api/19970).

## October 14 retrieval guidance update

Navigraph's [latest-OFP guidance](https://forum.navigraph.com/t/fetching-a-users-latest-ofp-data/5297), updated October 14, 2026, recommends Navigraph Alias, an identifying `client` parameter, and `json=v2`. Older `json=1` remains supported with formatting limitations. Retrieve in response to user action; do not poll latest OFPs to detect new plans. This response format is distinct from authenticated SimBrief API v2. [Follow-up evidence and adapter consequences](launch-dependencies-followup.md#confirmed-facts-current-simbrief-retrieval-guidance).

## Extension plan: engineering inference

| Change | Why and acceptance |
| --- | --- |
| Separate provider adapter from text rendering | Obtain one complete raw response, validate, then derive views from an immutable leg/revision snapshot. Existing human-readable tools may remain compatibility views. |
| Add validated dispatch requests | Map explicit units, defaults, airframe identity and dates into the selected API; preserve user-approved inputs. |
| Add generation lifecycle | Prepare → authorized submit → waiting/authentication → retrieve → correlate. Use receipts and persisted state, not blind timeout retries. Do not poll the latest-OFP endpoint for completion; use a documented authorized generation lifecycle or explicit user refresh. |
| Add explicit identity handling | Keep internal trip/leg/revision, external request identity, and documented `static_id` distinct. Upstream optional `id` is not a verified substitute for `static_id`. |
| Parse complete runway analysis | Preserve runway-specific results, nested arrays/maps, messages, units, zeros, and all alternative/selected conditions. Validate against real launch-aircraft responses. |
| Add aircraft capability catalog | Use published SimBrief profile metadata; never infer engine/rating compatibility from ICAO code alone. |
| Add errors and freshness | Distinguish missing plan, unsupported performance, access denied, malformed response, stale data, waiting user, and unknown submission outcome. |
| Expose dispatcher through MCP | External task-level tools call the Deep Agent and adapter; a separate internal MCP subprocess is optional, not required. Hosting/authentication remain DISC-05. |

Recommended order: obtain current API documentation and authorized sample → validate raw schema and identities → implement adapter/snapshots → implement generation lifecycle → integrate agent. This avoids committing to PHP or inventing a REST generation endpoint.

## Conflicts and unknowns

The earlier design made the legacy popup sound universal. It is one documented path; API v2 may change the recommended implementation. Its complete specification and generation permissions were not available in this inspection.

No authenticated current A20N/A21N response was retrieved. Actual runway-analysis nesting, explicit N1 availability, exact engine/rating mapping, account access, identifier retention, generation/reconciliation, and Infinite Flight import remain unverified. No upstream tests were run and no code was installed or changed.

## Implications and next evidence

DISC-03's public source review is complete; live acceptance remains blocked on authorized documentation/access. Ask Navigraph, when Hudson authorizes contact, for: API v2 developer documentation; authentication/scopes for OFP retrieval and generation; personal-use eligibility; job/status/receipt semantics; static/plan identity and retention; complete runway-analysis schema including explicit N1/EPR availability; and supported access to custom airframes. This is an inquiry checklist, not a sent message.

Retrieve a user-authorized launch-aircraft OFP without selecting an arbitrary public Pilot ID. Preserve sanitized raw evidence. Require both latest-plan and separate-leg retrieval cases before claiming multi-leg readiness.

## First authorized retrieval

A subsequent user-requested fetch succeeded for a B38M plan. The [observation](first-authorized-ofp.md) establishes actual nested runway structure and empty target fields for that response. The earlier no-sample findings remain accurate for A20N/A21N; generation and multi-leg behavior are still unverified.
