# Backlog

Status: planning, October 30, 2026. This file is the work-management source. All work below is **not started** unless explicitly updated. Creating the plans does not authorize execution of every item.

Owner convention: Hudson owns product, cost, and authority decisions; the implementing agent owns an explicitly started engineering item. No deadlines or delegated workers are assigned. Keep work focused to one session; split an item when findings reveal a larger independent scope. Record evidence and blockers on the item, without duplicating decisions elsewhere.

## Research and decisions

### DISC-01 — Enumerate launch variants

- **Status:** Partially researched October 30, 2026. Public SimBrief catalog and official Infinite Flight neo LEAP/PW engine families captured in the [coverage register](aircraft-coverage.md); A321neo engine choice follows livery. Exact ratings, profile/livery mapping, and ceo scope remain open. See [professional thrust research](research/professional-thrust-sources.md).

- **Outcome:** Know exactly which A320/A321neo aircraft are in the launch set.
- **Dependencies:** None.
- **Work:** Inspect current official Infinite Flight fleet/update information and SimBrief supported profiles. Present the exact variant/engine mapping and clarify any material scope ambiguity with Hudson.
- **Acceptance/evidence:** Sourced inventory and matching profile candidates recorded in `aircraft-coverage.md`; user decision recorded here if A320 versus A320neo inclusion needs clarification.
- **Boundary:** No aircraft support claim, installation, or provider purchase.

### DISC-02 — Establish launch thrust-resolution paths

- **Status:** Public-source assessment recorded October 30, 2026; numerical acceptance **blocked** on exact engine mapping, current authorized data/tool access, and a worked reference. See [professional thrust research](research/professional-thrust-sources.md). No aircraft support established. Focused follow-up: DISC-07.

- **Outcome:** Identify how each launch aircraft's SimBrief solution becomes a manual engine target.
- **Dependencies:** DISC-01.
- **Work:** Inspect raw takeoff performance data for explicit targets, including nested fields. If absent, locate an applicable engine/rating reference or supported calculation. Determine required conditions, units, guidance, and simulator translation limits.
- **Acceptance/evidence:** Per-aircraft method and source; a reproducible worked case or a precise missing-data blocker. Distinguish researched, calculated, and simulator-observed values.
- **Boundary:** Do not substitute generic FLEX/derate percentages or throttle tables for an applicable target-resolution method. No fabricated numerical target.

### DISC-03 — Verify supported SimBrief generation and retrieval

- **Implementation pass started October 30:** User authorized local implementation and verification. See [build contract](implementation/simbrief-build-spec.md) for acceptance, operation boundaries, and current access findings. Generation acceptance remains blocked; no story closure claimed.

- **Status:** Source/document inspection completed October 30, 2026; live acceptance **blocked** on authorized API documentation/access and sample plans. [Findings](research/simbrief-extension.md) include API v2 access evidence, so legacy popup generation is not assumed to be the only integration path. Focused follow-up: DISC-06.

- **Outcome:** Know the authorized generation path, authentication handoff, identifiers, and multi-leg retention behavior.
- **Dependencies:** None; live work requires existing access or authorization.
- **Work:** Inspect official docs and existing community server; identify reusable retrieval code and requirements for generation access. Check how a generated result is correlated and retrieved after disconnect.
- **Acceptance/evidence:** Proposed operation contract, access requirements, handoff/resumption flow, and plan-identity semantics, with source links. Record access as unavailable if absent.
- **Boundary:** No API-key request message, account changes, unattended-authentication workaround, remote fork, or spending without authority.

### DISC-04 — Assess flight and simulator parking data

- **Status:** Provider assessment completed October 30, 2026; grounded gate-to-spawn acceptance **blocked** pending representative provider data and simulator mapping. See [comparison and evaluation plan](research/flight-data-sources.md). No provider selected or spending authorized. Focused follow-up: DISC-08.

- **Outcome:** Identify viable flight/gate sources and how to map them into actual simulator positions.
- **Dependencies:** None.
- **Work:** Compare structured flight sources with airline/airport references and research fallback. Inspect date/segment identity, gate freshness, FBO coverage, simulator position data, permitted access, and cost.
- **Acceptance/evidence:** A recommended source approach and a grounded gate-to-spawn example; explicit approximate/unavailable cases; provider cost/access decision if needed.
- **Boundary:** FlightAware is a candidate, not selected. No paid subscription or unrestricted scraping commitment.

### DISC-05 — Establish client connection path

- **Outcome:** Know how Codex, ChatGPT, and Claude will call one dispatcher service.
- **Dependencies:** None.
- **Work:** Verify current official transport/authentication requirements for intended client environments, account availability, and timeout behavior. Compare local access and authenticated HTTP hosting.
- **Acceptance/evidence:** Per-client feasibility matrix; proposed first development client; host/deployment decision needed for remaining clients. Do not equate protocol support with a live connection.
- **Boundary:** No public endpoint, deployment, account-permission change, or paid hosting.

## Implementation preparation

### DISC-06 — Resolve authorized SimBrief API path and actual performance schema

- **Implementation pass started October 30:** User authorized local implementation and verification. See [build contract](implementation/simbrief-build-spec.md) for acceptance, operation boundaries, and current access findings. Generation acceptance remains blocked; no story closure claimed.

- **Observed October 30:** Authorized Alias retrieval succeeded for the latest B38M KIAD–KEWR plan. Eight nested takeoff runway entries; target fields empty on every entry. [Observation](research/first-authorized-ofp.md). Neo sample, generation, and multi-leg acceptance remain blocked; account identity is not recorded in tracked research.

- **Progress October 30:** Current October 14 guidance establishes Alias + `client` + `json=v2` and user-triggered retrieval, without latest-plan polling. This format is distinct from authenticated API v2. Actual OFP schema and generation lifecycle remain blocked on user data/access. [Follow-up](research/launch-dependencies-followup.md).

- **Outcome:** Choose the supported integration from current documentation and real launch-aircraft data.
- **Dependencies:** DISC-03; user-authorized access/documentation. External contact requires explicit permission.
- **Acceptance/evidence:** API version and allowed operations; authentication/generation lifecycle; actual plan/static identity behavior; sanitized launch OFP runway-analysis shape; explicit finding on N1/EPR availability. Use the inquiry checklist in the [research](research/simbrief-extension.md).
- **Boundary:** No guessing private endpoints, contacting Navigraph, submitting live dispatches, or reading arbitrary users' OFPs without authority.

### DISC-07 — Establish professional launch-engine target access

- **Inventory October 30:** Exact engines resolved from EASA/FAA records (United A321neo N14507: A321-271NX, PW1133G-JM). No public FLEX→N1 schedule exists for any launch engine; only FlyByWire's simulation covers LEAP-1A26 (candidate). PW and A321neo-LEAP are blocked pending D-09. [Inventory](research/thrust-source-inventory.md).
- **Focused follow-up:** Temperature-ratio/pressure units and early FBW change history inspected. Manufacturer dataset provenance and exact rating applicability are not established; simulator engine-model tuning is separate from target correctness. [Evidence](research/launch-dependencies-followup.md#confirmed-facts-open-source-n1-method-limits).

- **Progress October 30:** Inspected a pinned FlyByWire A320neo N1-limit algorithm and actual caller; [findings](research/integration-blueprint.md#concrete-open-source-thrust-finding). Concrete inputs and table logic exist, but professional provenance, exact engine/rating mapping, and Infinite Flight equivalence remain unverified. Numerical acceptance remains blocked.

- **Outcome:** Determine whether an applicable professional source can supply the manual target required for launch.
- **Dependencies:** DISC-01/02; exact engine/rating identity. Provider contact/purchases require separate authority.
- **Acceptance/evidence:** Documented exact neo engine coverage, source revision, target output, existing-FLEX compatibility, API/export rights, price/access, and one reproducible worked case or precise blocker. Start with applicable free/open technical references and engine-specific open-source methods, assessing provenance and validation against the professional standard. Use [the free-first strategy](research/free-first-strategy.md); professional paid access is an explicit exception if needed, not the default integration.
- **Boundary:** No assumption-based fallback or combination of incompatible FLEX, V-speeds, and targets. No aircraft support claim before simulator verification.

### DISC-08 — Evaluate dated flight/gate coverage and stand mapping

- **Progress October 30:** One free Avinor OSL response returned 34 departures including dated gate observations; [evidence](research/evidence/avinor-osl-observation.json). No simulator stand match or broad date/geographic coverage established. Official IF v2 airport response has no stand list. [Findings](research/launch-dependencies-followup.md).

- **Outcome:** Make a provider recommendation from real representative cases rather than marketing field lists.
- **Dependencies:** DISC-04; permitted trial/existing access, any spending approval, and simulator position evidence.
- **Acceptance/evidence:** Execute the bounded sample in [flight-data research](research/flight-data-sources.md), starting with free airline/airport/open sources under [the source strategy](research/free-first-strategy.md); measure date horizons, discovery, nullable gates, latency/cost, retention rights, and one real gate-to-simulator mapping. Compare structured free allowances or paid plans only for demonstrated coverage/maintenance gaps; do not silently approve purchases.
- **Boundary:** No provider selection by price alone, indefinite raw-data retention without rights, historical gate relabeled as future assignment, or claim that a mapped stand is unoccupied.

### SETUP-01 — Install application quality and validation foundations

- **Outcome:** Application work starts with actual runnable checks and durable product evidence.
- **Dependencies:** Language/runtime decision D-01; implementation authorization.
- **Work:** Run `python3 Tools/CodexSkills/scripts/bootstrap-code-quality.py <repo>` from the workspace root when supported source/manifests exist. Add pinned language-matched dead-code checks (Vulture for Python; Fallow for JS/TS), one local command and the same PR CI command. Add `tabellio.validation.json`, actual-PR-head product-validation CI, and durable evidence per validator invocation.
- **Acceptance/evidence:** Actual files/commands installed; meaningful local pass recorded on the candidate; required evidence is `passed`, `failed`, or `blocked`; missing/empty evidence is blocked. Before human code review bind acceptance to exact candidate commit; publication requires pushed-head validation.
- **Current setup note (October 30, 2026):** The workspace quality bootstrap was run before the move into Products. It exited 1 with `ValueError: No supported source files found` and installed no files. This repository contains planning Markdown only; no hooks, validators, CI, or `tabellio.validation.json` are installed. After language/source setup, rerun `python3 Tools/CodexSkills/scripts/bootstrap-code-quality.py Products/InfiniteFlightDispatcher` from the workspace root. This is a recorded setup blocker, not an exemption for future product code.
- **Boundary:** Do not invent runtime code or a fake validator merely to satisfy setup. No commit/push without approval.

## Implementation

### BUILD-01 — Define shared flight and result contracts

- **Outcome:** All components use one consistent version of each flight leg.
- **Dependencies:** SETUP-01; established findings from DISC-01–04.
- **Acceptance/evidence:** Typed validated inputs/results with explicit units, sources, revisions, unknowns, per-component status, and retained original data. Changes invalidate dependent outputs. Representative raw reports parse without losing messages or nested data.
- **Boundary:** No implicit unit guessing or model-owned numerical truth.

### BUILD-02 — Add Deep Agents dispatcher and MCP run management

- **Outcome:** A client can request preparation, answer clarification, and resume a saved run.
- **Dependencies:** BUILD-01, DISC-05; selected provider/budget and execution authority.
- **Acceptance/evidence:** One coordinator uses bounded tools; persistent run/leg identity; prepare/status/resume/briefing/refresh/cancel contract; a real low-risk host request and interruption recovery. Record model/API costs and latency.
- **Boundary:** No arbitrary shell access, automatic purchases, infinite research loops, or extra agent hierarchy without demonstrated need.

### BUILD-03 — Implement flight research and spawn guidance

- **Outcome:** The user receives flight identity, schedule, and actionable airport-position guidance.
- **Dependencies:** BUILD-01–02, DISC-04; selected source access.
- **Acceptance/evidence:** Dated airline-flight and private-FBO cases; separate reported position and simulator recommendation; local/UTC times; source timestamps; approximate/unavailable handling; refresh of changed gate assignments.
- **Boundary:** Do not invent assignments or claim the simulator has spawned the aircraft.

### BUILD-04 — Extend SimBrief preparation, generation, and retrieval

- **Implementation pass started October 30:** User authorized local implementation and verification. See [build contract](implementation/simbrief-build-spec.md) for acceptance, operation boundaries, and current access findings. Generation acceptance remains blocked; no story closure claimed.

- **Outcome:** Agreed inputs produce retained plans for every trip leg.
- **Dependencies:** BUILD-01–02, DISC-03; required developer/user access.
- **Acceptance/evidence:** Live plan matches inputs; unmodified response and normalized snapshot preserved; both legs survive latest-plan changes; authentication waiting/resume; duplicate-safe recovery after uncertain timeout.
- **Boundary:** No promise of unattended generation before verified support; no plan-import claim without simulator evidence.

### BUILD-05 — Implement launch-aircraft thrust resolvers

- **Progress October 30:** `estimate_takeoff_n1` MCP tool implemented for A20N/A21N TOGA/FLEX under the D-09 labeled-estimate decision. Engines: PW1124G1/1127G/1129G/1130G/1133G-JM (EASA flat ratings), LEAP-1A26 (FlyByWire simulation), LEAP-1A32/33/35A (assumed corner point). 19 local tests pass, including a hand calculation from FlyByWire's source. A real MCP stdio call on the saved B38M snapshot returned `unsupported_profile`. No real neo OFP or Infinite Flight calibration has been run yet.
- **Extended October 30 (Hudson request):** B38M/LEAP-1B28 added outside launch scope, using the same method plus Boeing fixed derates. On the real saved B38M snapshot (D-TO2, SEL 48, OAT 15) the MCP tool returned 0.857 × full-thrust N1 (range 0.800–0.902), matching a hand calculation; 28 local tests pass.

- **Outcome:** Each launch aircraft's SimBrief takeoff solution yields supported manual guidance.
- **Dependencies:** BUILD-01, BUILD-04, DISC-02.
- **Acceptance/evidence:** Aircraft-specific inputs, modes, engine target, source/method, valid conditions, and guidance implemented; missing data returns unavailable. Optional throttle estimates remain separate from targets. Changed performance inputs invalidate prior guidance.
- **Boundary:** No generic family support claim without per-aircraft applicability checks.

## Verification and release

### VERIFY-01 — Verify each launch-aircraft translation

- **Outcome:** Determine which aircraft meet the accepted support definition.
- **Dependencies:** BUILD-05.
- **Acceptance/evidence:** Required worked and simulator cases for each aircraft, matching profile/version and conditions; record passed/failed/blocked plus original evidence in sanitized `docs/evidence/` artifacts. Update coverage only from these results.
- **Boundary:** Unit tests, model agreement, or a slider/N1 curve alone do not establish all translation/performance claims.

### VERIFY-02 — Verify complete preparation in all intended clients

- **Outcome:** Hudson can use Codex, ChatGPT, or Claude to complete the accepted workflow.
- **Dependencies:** BUILD-02–05, VERIFY-01; authorized host access.
- **Acceptance/evidence:** Real incomplete request, focused clarification, airline and private multi-leg cases, prominent spawn/thrust response, saved plan identity, partial failure, refresh, and resumption. Track each client's observed result separately.
- **Boundary:** Formatted server output alone does not prove host rendering; a connected client alone does not prove flight preparation.

### VERIFY-03 — Verify Infinite Flight handoff and release readiness

- **Outcome:** Know what imports and what Hudson must still do manually.
- **Dependencies:** VERIFY-01–02.
- **Acceptance/evidence:** Observed import field matrix, remaining manual setup, gate selection, usable thrust instruction, cost/latency, and exact-candidate product-validation result. All required launch criteria pass before declaring release-ready.
- **Boundary:** Do not mark unknown import coverage or required cost telemetry as passed. No publication/deployment/merge authority implied.

## Expansion

### EXPAND-01 — Select and deliver the next aircraft batch

- **Outcome:** Expand supported translations toward majority fleet coverage.
- **Dependencies:** Launch readiness; refresh current fleet/update evidence.
- **Acceptance/evidence:** Prioritize recently updated aircraft, document useful shared methods, create focused per-aircraft work items with inputs/guidance/verification, and report supported counts against a named fleet snapshot and denominator.
- **Boundary:** No claim that every aircraft has a compatible SimBrief takeoff solution. Preserve explicit unsupported/not-applicable states.

## Open decisions

The [integration blueprint](research/integration-blueprint.md) defines proposed internal operations, shared result envelopes, MCP boundaries, and the immediate investigation sequence. It does not authorize implementation or claim source completeness.

These are unresolved, not implementation blockers for writing the plans. Research should produce concrete recommendations where applicable.

| ID | Decision | Owner | Needed before |
| --- | --- | --- | --- |
| D-01 | Implementation language/runtime; Python accepted by Hudson October 30, 2026 | Hudson, informed by implementing agent | SETUP-01 |
| D-02 | Exact launch variant set and matching profiles | Hudson after DISC-01 | Launch resolver implementation |
| D-03 | Model provider, development budget, and permitted paid calls | Hudson | Live agent runs |
| D-04 | Flight-data provider/access and budget. **Decided October 30, 2026:** FlightAware AeroAPI Personal tier (no minimum, monthly free credit, personal use only). Live KIAD tests and tool plan in [flight tools plan](implementation/flight-tools-plan.md) | Hudson after DISC-04 | Provider-dependent live research |
| D-05 | Intended weather/time default and handling of real-versus-simulator differences | Hudson | Final dispatch/performance defaults |
| D-06 | Local/hosted access, authentication, hosting budget, first development client | Hudson after DISC-05 | Host access/deployment |
| D-07 | Default generation behavior after “prepare a flight,” and when to ask before submission | Hudson | Mutating dispatch tool policy |
| D-08 | Fallback preferences for unavailable gates and thrust | Hudson | Final briefing defaults |
| D-09 | Professional performance-data/tool access and any associated license/budget. **Decided October 30, 2026:** labeled simulation-grade estimates are acceptable (see [goal amendment](goal.md#release-scope)); professional access is not being pursued now. [Source inventory](research/thrust-source-inventory.md) | Hudson after DISC-07 | Verified launch thrust targets |

Existing commitments: goals and launch/expansion priorities are accepted in `goal.md`. Local repository/document creation is authorized. Commit, push, paid operations, external messages, account/access changes, and deployment are not authorized by that setup.

## Planning setup checks — October 30, 2026

- **Passed:** local Git initialized on `main`; no commits or remotes; one canonical worktree at the documented project home.
- **Passed:** all seven initial Markdown documents checked for existing local link targets, balanced code fences, and whitespace. No runtime behavior was tested or claimed.
- **Blocked:** application quality bootstrap, as recorded under SETUP-01.
- **Blocked:** workspace-wide structure audit exited 1 for prunable registrations in `Products/Marketing/IntelIPGTM`, `Products/Marketing/IntelIPGTMOpenAI`, and `Products/Marketing/IntelIPGTMAgentDesk`. Other reported structure checks passed. This task did not modify those checkouts or worktree registrations; resolving them requires a separate preservation check under workspace worktree rules. The new repository has no prunable registration.

## Python implementation pass — October 30, 2026

Python approved by Hudson. [Usage and limitations](implementation/simbrief-usage.md).

| Story | Current outcome | Remaining acceptance |
| --- | --- | --- |
| DISC-03 | Partial; current generation paths inspected | Authorized generation documentation/access, lifecycle and retention verification |
| DISC-06 | Partial; real B38M response retrieved through implemented MCP | Actual neo response and generation identity/schema evidence |
| SETUP-01 | Local foundation installed: bootstrap, pinned Vulture, locked Python environment, manifest and PR-head CI; local checks pass | Exact-commit validation and hosted CI not available; no commit authorized |
| BUILD-01 | SimBrief request, raw snapshot, and structured takeoff subset implemented | Remaining shared dispatcher contracts and generation correlation |
| BUILD-02 | Local stdio MCP operations and SQLite snapshot persistence implemented | Deep Agents coordinator, conversational run management, intended client acceptance |
| BUILD-04 | Partial; preparation, live existing-plan retrieval, immutable local leg/revision storage | Generation, complete provider input surface, full input correlation, auth/recovery, live two-leg retention |

Five local tests cover nested takeoff selection and zeros, persistence/revision isolation, input/mismatch errors, failed provider requests without retry, and actual stdio MCP calls. These are local/fixture checks; only the recorded B38M retrieval is a live provider result. [Live MCP observation](evidence/simbrief-mcp-retrieval.json). The validator records local success but an overall blocked result, with timestamped candidate/check artifacts in Git-ignored `artifacts/validation/`. No stories are closed by partial acceptance.

## Other components — first case selected October 30, 2026

Hudson selected **Dulles–Newark, United A321neo**. Date remains unspecified; October 30 is a research assumption only. [Workstream contract and new findings](implementation/flight-and-thrust-workstreams.md) own the details.

### DISC-09 — Resolve the dated United IAD–EWR flight

- **Status:** In progress; official static pages did not expose a dated flight. Candidate search results are not accepted flight identities. **October 30:** AeroAPI returned the dated United KIAD→KEWR nonstops (UA1359, UA2396, UA2823, UA1831, UA1997) with gates and aircraft; no A321neo flew this route between Oct 28 and Oct 31. The SimBrief plan's UA2408 is really DEN→IAD. Flight selection awaits Hudson. See [flight tools plan](implementation/flight-tools-plan.md#evidence-this-plan-is-built-on).
- **Outcome:** A dated operating flight and its schedule, with simulator aircraft preference kept separate from real equipment.
- **Acceptance:** Official airline/airport observation matching both airports and date; preserve codeshares, actual equipment or unknown, local/UTC times, and source time. Report conflicts rather than choose by flight number alone.
- **Dependencies:** Intended departure date; rendered official page or permitted provider access.
- **Boundary:** No paid account, provider adoption without provenance, fabricated flight number, or assertion that the selected simulator aircraft operates this real segment.

### DISC-10 — Ground that flight's gate and simulator stand

- **Status:** Not verified. Current Infinite Flight Live data retention restrictions recorded; archived airport layouts cannot prove current stands.
- **Outcome:** Actionable spawn guidance with the real gate and simulator stand distinguished.
- **Acceptance:** Dated gate evidence and observed matching selectable stand, or an explicit mapping-unavailable result. Record aircraft suitability and scenery version; never imply occupancy.
- **Dependencies:** DISC-09 and actual simulator position evidence.
- **Boundary:** No persistence of Live API responses contrary to source rules, historical gate relabeled current, or guessed gate assignment.

### DISC-11 — Establish United A321neo PW thrust applicability

- **Status:** Engine manufacturer confirms United's GTF selection; exact simulator rating, matching OFP, and reference target remain unavailable. **October 30:** A community member stated on October 6, 2026 that Infinite Flight has "no way to map the flex temp to a thrust value in game" ([thread](https://community.infiniteflight.com/t/possible-a321neo-official-guide/1323434)). A community A321neo guide gives only throttle-%/N1 rules of thumb ([guide](https://community.infiniteflight.com/t/airbus-a321neo-flying-guide/1323497)), which are excluded as a method. Both are unverified community statements; Hudson's in-simulator observation of the PERF/E-WD behavior remains the required first check.
- **Outcome:** A reproducible applicable takeoff target and usable manual simulator guidance.
- **Acceptance:** Exact model/engine/profile, matching A21N takeoff solution, professional applicable PW method/reference, and observed simulator indication/setting. First check native PERF behavior.
- **Dependencies:** DISC-01/02/07 and a matching OFP; generation API access is not required if the user supplies or normally generates the plan.
- **Boundary:** No LEAP algorithm applied to PW, no generic slider conversion, no family-wide support claim.

BUILD-03 and BUILD-05 remain incomplete. The new technology policy governs new adoption; existing research candidates are not automatically approved.
