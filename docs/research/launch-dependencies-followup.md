# Launch dependencies: focused follow-up

Research date: October 30, 2026. Scope: DISC-01, DISC-06, DISC-07, DISC-08. Public documentation/source inspection and one unauthenticated Avinor feed request. No paid calls, dispatch submissions, account changes, simulator execution, or application implementation.

## Question and decision informed

Which remaining source gaps can be resolved without paid services, and what concretely blocks the first aircraft-specific end-to-end case?

## Conclusion

There is a working free source of dated flight/gate observations for one airport region, a current SimBrief retrieval contract, and concrete engine-family distinctions for launch. There is still no verified thrust translation or gate-to-simulator mapping. Start the next case with an existing user-supplied neo OFP and its exact Infinite Flight aircraft/livery, while authorized generation documentation remains a separate dependency.

## Confirmed facts: launch aircraft and native capabilities

The official fleet pages identify:

| Infinite Flight aircraft | ICAO | Listed powerplants | Unresolved identity |
| --- | --- | --- | --- |
| A320neo | A20N | CFM International LEAP-1A; Pratt & Whitney PW1100G-JM | Exact engine/rating and livery mapping |
| A321neo | A21N | CFM International LEAP-1A; Pratt & Whitney PW1100G | Exact engine/rating for each livery |
| A320-200 | A320 | CFM56-5B; IAE V2500 | Whether ceo belongs in the initial launch scope |

Sources: [A320neo fleet](https://infiniteflight.com/fleet/a320neo), [A321neo fleet](https://infiniteflight.com/fleet/a321neo), [A320-200 fleet](https://infiniteflight.com/fleet/a320-200). Engine families do not identify certified rating suffixes.

The official [A321neo preview](https://www.infiniteflight.com/blog/a321neo-live-preview-recap) says engine choice follows the airline/livery; airlines operating both receive one choice in the simulator. This establishes that policy for the A321neo, not automatically for every A320neo livery.

The [26.4 release](https://www.infiniteflight.com/blog/infinite-flight-26-4-and-the-a321neo) documents an interactive MCDU, SimBrief briefing integration, and imported V-speeds displayed on the HUD/PFD. It does not establish an available FLEX-to-N1 calculation. Inspect the native PERF behavior before duplicating functionality. A fleet-page update field predating the documented A321neo release is insufficient to rank update recency; use dated release history instead.

## Confirmed facts: current SimBrief retrieval guidance

Navigraph's [latest-OFP guidance](https://forum.navigraph.com/t/fetching-a-users-latest-ofp-data/5297), first post updated October 14, 2026, recommends Navigraph Alias, an identifying `client` parameter, and `json=v2` for new integrations:

```text
https://www.simbrief.com/api/xml.fetcher.php?username={alias}&client={application_name}&json=v2
```

`json=1` remains supported but has formatting issues. Fetch in response to user action; repeated polling to detect newly generated plans is prohibited by that guidance. `json=v2` is a response-format selection, distinct from the newer authenticated SimBrief API v2 and its privately supplied generation documentation.

No actual user OFP was obtained. Available tool metadata, matching local MCP configuration names, relevant environment-variable presence, and project sample filenames did not expose a usable account binding or existing OFP. No secret values were retrieved. This is a narrow access observation, not a claim that no credentials exist elsewhere.

### Proposed adapter consequences

- Add Alias and application identity; preserve complete JSON v2 payloads before normalization.
- Make latest-plan refresh explicitly user-triggered. Do not implement a latest-OFP polling loop as generation reconciliation.
- Generation completion/recovery must use the documented authorized lifecycle when obtained; a refresh action does not prove a specific generation succeeded.
- Obtain one A20N/A21N XML/JSON export or a user-provided Alias for authorized retrieval, then establish actual runway-analysis structure and whether an explicit N1 target exists.

## Confirmed facts: open-source N1 method limits

The prior [algorithm inspection](integration-blueprint.md#concrete-open-source-thrust-finding) is pinned to FlyByWire commit `66021c24448c44399a8ff569eb14715b6b26558e`. Additional inspection established:

- [EngineRatios.hpp](https://github.com/flybywiresim/aircraft/blob/66021c24448c44399a8ff569eb14715b6b26558e/fbw-common/src/wasm/fadec_common/src/EngineRatios.hpp) defines ambient temperature in degrees Celsius, pressure in hPa, and `theta2 = ((273.15 + temperature) / 288.15) * (1 + 0.2 * Mach²)`. The N1-limit conversion uses the square root of this temperature ratio plus bleed correction; it is not a FLEX-percentage rule.
- The A32NX engine simulation configuration specifies 27,120 lb static thrust. That is a simulator parameter, not proof of an applicable certified LEAP rating or Infinite Flight equivalence.
- First-party [PR 6560](https://github.com/flybywiresim/aircraft/pull/6560) describes changing limits from N1 to corrected-N1 tables, acknowledges engine-model limitations reaching the targets, and requests real-world N1 references for testing. [PR 7200](https://github.com/flybywiresim/aircraft/pull/7200) subsequently adjusts the engine model to the limits and describes simulator tests.

The inspected source and these change descriptions do not establish the underlying manufacturer's dataset, revision, or applicability to our exact engines. This is an inspectable simulation method, not yet the professional reference required for acceptance. Numeric target correctness and a simulator engine's ability to attain it are separate questions. Do not run this method for PW engines or A321neo by family-name analogy.

## Confirmed facts: free flight and gate data

### Observed Avinor result

Avinor documents a free public XML feed covering 43 Norwegian airports, excluding Torp. Gate values are optional. Its short rolling time window is not a historical archive or a guarantee of future gate assignment. Respect a minimum three-minute request interval; cache static dictionaries separately. Display **Flight data from Avinor**, linked to [Avinor](https://www.avinor.no), near results. [Feed documentation](https://partner.avinor.no/en/services/flight-data/).

One request to the documented endpoint succeeded without credentials or payment:

```text
https://asrv.avinor.no/XmlFeed/v1.0?airport=OSL&TimeFrom=1&TimeTo=7&direction=D
```

The response contained 34 departures with feed `lastUpdate` of `2026-10-30T20:44:55.876526Z`. Selected observations were DY1310 to LGW, scheduled 17:45 UTC, gate F16; and KL1206 to AMS, scheduled 17:55 UTC, gate E15. Both were marked delayed with later departure-status times. Preserve scheduled, actual/status, and observation timestamps separately. The observed XML uses `flight_id` and `uniqueID`; do not rely solely on naming in documentation tables. [Extracted response evidence](evidence/avinor-osl-observation.json).

These are feed observations, not independently confirmed assignments or verified Infinite Flight stands. Coverage at Oslo does not establish coverage at Dulles.

### Other source findings

- [BTS on-time data](https://transtats.bts.gov/ONTIME/) offers free historical US domestic flight/timing data; the inspected availability ran January 1995 through August 2026. Its [reporting directive](https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-40-technical-directive-reporting-time) specifies gate departure/arrival *times*, not physical gate numbers. It cannot fill the gate-ID gap.
- [SFO flight status](https://www.flysfo.com/flight-status) states a window of 12 hours ahead and four hours behind, in local Pacific time. Static retrieval did not expose flight records; this was not a gate-data success.
- [Dulles arrivals/departures](https://www.flydulles.com/arrivals-and-departures) returned a page shell without flight observations in this inspection. No Dulles gate result was obtained. Its [general aviation information](https://www.flydulles.com/flight-information/general-aviation-information) points toward FBO operators; that is not an assigned parking position.

## Confirmed facts: simulator mapping boundary

The documented Infinite Flight [v2 airport-information response](https://infiniteflight.com/guide/developer-reference/live-api/airport-information) includes airport identity, coordinates, elevation, timezone, and facility flags. It does not list gates or parking stands. That endpoint alone cannot map a provider gate string to a selectable spawn. No authenticated request was made.

The October 5 [Live API v3 preview](https://community.infiniteflight.com/t/live-api-v3-preview-updates/1322130) offers a testing path for account-created OAuth clients. Its simulator-organization schedules must not be mistaken for real airline schedules. No OAuth client was created or permission changed.

## Inference and recommendation

A low-cost first vertical case should combine an existing neo OFP, exact aircraft/livery/engine identity, one dated flight observation, and a user-observed selectable simulator stand. Oslo is a concrete free-data candidate if it fits Hudson's intended flight. It is not a required product geography or a selected global provider.

Prioritize the A320neo LEAP profile for the first method assessment because inspectable code exists. This is an engineering proposal; it does not narrow the accepted launch family or establish support. Professional applicability and simulator verification remain required. PW and A321neo methods need separate investigation after the first exact profile is identified.

## Conflicts, unknowns, and stop condition

- Launch ceo inclusion, exact engine ratings, and all livery mappings remain unresolved.
- Current OFP N1 availability and the authorized generation lifecycle remain unverified.
- No professional reference target or simulator thrust observation exists for this project.
- Broad historical/future gate coverage and one real gate-to-spawn mapping remain open.

The public-source follow-up is complete at this evidence layer. Further productive research depends on the named OFP/aircraft/reference inputs; it should not repeat the provider survey. No aircraft is supported and no end-to-end release is demonstrated.
