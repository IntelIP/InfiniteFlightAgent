# Integration investigation and proposed contracts

Date: October 30, 2026. Status: researched design, not implementation. Extends [SimBrief findings](simbrief-extension.md), [flight data assessment](flight-data-sources.md), and [free-first strategy](free-first-strategy.md). No application code, dependencies, account integrations, or live plans were created.

## Question and decision informed

Do we have all required sources, and how should SimBrief extensions, other MCP/data tools, and final thrust calculations connect?

## Conclusion

We have enough source knowledge to define an integration boundary and continue targeted investigation. We do not have all launch data/access. Preserve one external dispatcher MCP service. Internally use ordinary functions for simple HTTP/data/calculation operations and MCP clients only for actual external MCP servers. MCP is an interface protocol, not a data provider; NOAA, airport files, and engine lookup tables do not each need a separately operated server.

See the [focused follow-up](launch-dependencies-followup.md) for newer retrieval guidance, observed Avinor data, engine distinctions, and provenance limits.

## Readiness by component

| Component | Evidence available | Missing evidence/access | Can proceed now |
| --- | --- | --- | --- |
| SimBrief adapter | Pinned MIT retrieval source, legacy generation docs, newer API access path | Authorized generation contract, current raw launch-aircraft performance, identity/retry behavior | Define adapter and result contracts; avoid inventing API v2 endpoints |
| Airport and weather | Public OurAirports downloads and AWC API candidates | Endpoint-specific limits/freshness and representative integration checks | Design straightforward adapters and source records |
| Dated flights/gates | Provider comparison, free-source strategy, and observed OSL Avinor gates | Sustainable free coverage for historical/future gates; named flight and actual simulator stand mapping | Assess targeted first-party sources; retain partial/unavailable states |
| A320neo engine target | Pinned, inspectable FlyByWire N1-limit algorithm and caller | Dataset provenance, exact rating match, applicable professional reference, Infinite Flight behavior | Assess algorithm inputs and reference validation requirements |
| A321neo targets | User scope and SimBrief aircraft metadata | Per-engine/rating method and verification | Research exact variants; no family-wide assumption |
| Conversational hosts | MCP/agent architecture and current client-library documentation | Account-specific connections, transport/authentication and final rendering | Specify one external service; runtime/client acceptance remains separate |

## SimBrief extension boundary

The following are proposed internal operations, not already registered MCP commands:

| Operation | Inputs | Outputs/invariants |
| --- | --- | --- |
| `list_airframes` | Catalog version/cache policy | Supported metadata plus user/custom identity where permitted; metadata is not engine compatibility proof |
| `prepare_dispatch` | Leg revision; explicit aircraft, date/time, payload, route/options and units | Validated provider request, visible defaults, missing fields; no external write |
| `submit_dispatch` | Validated request, action authority, operation ID | Receipt or explicit waiting/unknown state; persist before retry |
| `reconcile_dispatch` | Saved operation/provider identifiers | Observed result, waiting, failed, or unknown; never infer success from timeout or poll latest OFPs to detect completion |
| `fetch_plan_snapshot` | Explicit provider plan/static identity | Unmodified payload, observed identity/time, immutable local snapshot reference |
| `extract_takeoff_solution` | Snapshot and selected runway/result identity | Complete selected conditions, thrust mode/FLEX, speeds, configuration, messages, units; missing fields explicit |

The existing 14 tools can remain human-facing compatibility views over a snapshot. Their formatted output is not the authoritative input to a calculator. Keep internal leg/revision identity separate from mutable external static identity. Current upstream source and access questions are owned by [the extension report](simbrief-extension.md).

## Other data and MCP integration boundary

Proposed tools:

- `find_flight_candidates`: date/route/aircraft constraints → dated operating flights plus codeshares, schedules, source and coverage status.
- `get_flight_observation`: specific operating flight/segment/date → scheduled/estimated/actual times, reported gate/terminal, observation time, unavailable fields.
- `get_airport_reference`: ICAO → airport/runway reference and source version. Keep community facts separate from certified analysis.
- `get_weather_observation`: station and relevant time → raw/decoded METAR/TAF with issue/validity/retrieval times; real observations and chosen simulator weather remain separate.
- `resolve_spawn`: reported gate/FBO plus simulator airport reference and aircraft → exact/approximate/suggested/unavailable spawn position with mapping evidence. No unobserved occupancy claim.
- `resolve_takeoff_target`: selected SimBrief solution plus exact aircraft profile and intended simulator conditions → supported engine target or blocked reason.

Every operation returns a small validated envelope: `status`, `data`, `source_refs`, `observed_at`, `validity`, `missing_inputs`, and `errors`. Include units beside values, applicable date/segment, and record/profile revisions. Gate changes affect parking; a weather/runway/aircraft/performance change invalidates the associated thrust result. Do not use a single global freshness flag.

If an external MCP server is selected, allowlist its relevant tools, namespace names, normalize its result through the same application contract, and store required data outside connection/session memory. Avoid letting untrusted tool text decide generation authority or claim aircraft support.

Current LangChain Python documentation describes `langchain.mcp.MCPAdapter` in `langchain[mcp]>=1.4.0` as beta, replacing the older standalone adapter. It supports discovering external MCP tools; returned structured content is carried in the tool-message artifact, which our integration must deliberately preserve. Pin compatible versions when the Python/runtime decision is made; do not add an old `MultiServerMCPClient` example by habit. [MCP connections](https://docs.langchain.com/oss/python/langchain/mcp/connections), [structured content](https://docs.langchain.com/oss/python/langchain/mcp/tools#structured-content), [migration](https://docs.langchain.com/oss/python/migrate/langchain-mcp-adapters).

This is an optional client layer for external MCP dependencies, not a requirement to wrap all internal tools. Deep Agents accepts ordinary tools. The curated [workflow evolution](</Users/hudson/Library/Application Support/AgenticEngineering/openwiki/workflow-evolution.md#from-discovery-to-structured-execution>) supports explicit code for established operations while retaining adaptive research for unresolved paths.

## Concrete open-source thrust finding

Inspected FlyByWire aircraft commit **`66021c24448c44399a8ff569eb14715b6b26558e`**. No code was executed, copied into the application, or used to produce guidance.

| Source surface | Confirmed behavior |
| --- | --- |
| [ThrustLimits_A32NX.hpp L19–113](https://github.com/flybywiresim/aircraft/blob/66021c24448c44399a8ff569eb14715b6b26558e/fbw-a32nx/src/wasm/fadec_a32nx/src/Fadec/ThrustLimits_A32NX.hpp#L19-L113) | Separate table ranges for TO, GA, CLB, and MCT; altitude and temperature corner/limit points; corrected N1 values |
| [Bleed calculation L153–214](https://github.com/flybywiresim/aircraft/blob/66021c24448c44399a8ff569eb14715b6b26558e/fbw-a32nx/src/wasm/fadec_a32nx/src/Fadec/ThrustLimits_A32NX.hpp#L153-L214) | Packs, nacelle anti-ice, wing anti-ice, operation, altitude, and temperature affect corrections |
| [limitN1 L216–325](https://github.com/flybywiresim/aircraft/blob/66021c24448c44399a8ff569eb14715b6b26558e/fbw-a32nx/src/wasm/fadec_a32nx/src/Fadec/ThrustLimits_A32NX.hpp#L216-L325) | Inputs: operation, altitude, ambient temperature/pressure, FLEX, packs, nacelle/wing anti-ice. Interpolates table values, resolves FLEX/ambient branch, converts corrected N1 through a temperature-ratio helper, adds bleed corrections |
| [EngineControlA32NX.cpp L1040–1085](https://github.com/flybywiresim/aircraft/blob/66021c24448c44399a8ff569eb14715b6b26558e/fbw-a32nx/src/wasm/fadec_a32nx/src/Fadec/EngineControlA32NX.cpp#L1040-L1085) | Caller supplies pressure altitude, latches FLEX state, computes TO/GA limits, and blends limits with Mach; a stand-alone lookup omits this contextual behavior |
| File header | GPL-3.0 marker; no professional/OEM validation or table provenance established by this source inspection |

FlyByWire identifies its A32NX as an A320neo LEAP simulation in its [official FAQ](https://docs.flybywiresim.com/aircraft/faq/). This does not establish the exact LEAP rating or Infinite Flight equivalence. The code is an inspectable candidate, not a certified/validated resolver for this project. A321neo and other engine/rating variants require separate evidence. Follow file-specific license notices before any reuse; [official licensing](https://www.flybywiresim.com/licenses/).

## Thrust calculation contract: proposal

Use an immutable selected takeoff solution plus a versioned aircraft profile. Establish exact input units from the actual caller/definitions and professional method. Airport elevation alone is not a substitute for the required pressure-altitude/ambient inputs. Separate actual temperature from assumed temperature and preserve air-conditioning/anti-ice configuration.

The resolver returns target indication/units, applicable static/rolling/speed condition, method/profile/source revision, supported bounds, manual instructions, and verification class. If data or applicability is missing, return a specific blocked reason. A candidate open-source result must not be exposed as a supported user thrust instruction before the professional-reference and simulator checks pass.

Calculation states: `missing_input`, `unsupported_profile`, `candidate_method`, `reference_verified`, `simulator_verified`. These describe evidence progression, not automatic aircraft support: the accepted support rule still requires the documented aircraft acceptance and evidence. Do not introduce numerical tolerance thresholds until the reference precision and intended claim are known.

## Next work sequence

1. Complete exact simulator/SimBrief engine mapping (DISC-01) and narrow the first method assessment to a specific launch profile.
2. Obtain authorized current SimBrief sample and API documentation (DISC-06), while completing the open-source algorithm provenance/input assessment (DISC-07).
3. Establish one dated airline gate → real simulator spawn mapping using free accessible sources (DISC-08). Preserve gaps in historical/future data instead of substituting assumptions.
4. Resolve runtime, model/budget, and external-action decisions already listed in the backlog. Install actual quality/validation foundations at SETUP-01 before application work.
5. Implement the snapshot/read-only path first, then generation/recovery, then a supported profile resolver, and finally complete host/simulator acceptance. A saved user-supplied OFP can unblock adapter research while developer access is pending; it does not satisfy automated generation acceptance.

## Unknowns and done condition for this investigation

These contracts establish no source selection, authenticated integration, independently verified gate assignment, professional reference result, numerical target, or aircraft support. The later follow-up records one successful public Avinor feed retrieval. The investigation has identified concrete reusable code, tool boundaries, required inputs, and specific access/data blockers. Further work should address these named gaps rather than repeat the vendor survey or assume every source needs its own MCP server.
