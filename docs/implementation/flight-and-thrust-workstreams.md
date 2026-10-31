# Flight research, gates, and thrust: first integrated case

October 30, 2026. User authorized advancing these components and selected Dulles–Newark, United A321neo. This is the simulator aircraft preference, not a verified claim that a matching scheduled flight uses that aircraft. Date was not supplied; October 30, 2026 is the explicitly stated research assumption, not an accepted dispatch date. No flight, gate, or thrust target is selected yet.

## Execution order

Flight identity and reported gates can be researched before SimBrief generation. Simulator stand mapping is a separate check. Thrust consumes an actual aircraft-specific takeoff solution, obtained from an existing OFP or normal user generation while API generation access is pending. These workstreams do not require changing the SimBrief generation-access decision.

## Flight-number research

Required input: origin, destination, intended local departure date, airline preference, simulator aircraft, and whether exact real-world equipment matching is required. Preserve requested simulator aircraft separately from reported operating aircraft.

Return operating flight number, marketing/codeshare numbers where known, airports, dated segment identity, scheduled/estimated/actual UTC times with local timezone, equipment, source, observation time, and any conflicts. A search result is a candidate; flight number alone is not an identity.

For this case, the official [Dulles board](https://www.flydulles.com/arrivals-and-departures) exposed no flight rows to static retrieval. [United flight status](https://www.united.com/en/us/flightstatus) returned a JavaScript-required page. No live airline/airport gate was established. A flight-discovery search surfaced UA2396 as a candidate; it is not selected or independently confirmed for the intended date. Other results for UA2147 conflicted on route, so its apparent IAD/EWR gate values must not be used. The prior SimBrief flight number is user-planned metadata, not proof of a real dated schedule.

Next verification: inspect the rendered official airline or airport flight-status page for the chosen date. If browser access is unavailable, record source unavailable and retain candidates; do not promote search snippets to confirmed flights. A paid provider is a separate choice only after this access/coverage gap is demonstrated.

## Gate and simulator spawn research

Return separate fields for reported departure gate, reported arrival gate, simulator spawn, mapping status, and source times. States: assigned/reported, not assigned, unavailable, conflicting; simulator mapping independently verified or unverified. Do not turn a previous flight's gate into a current assignment.

The historical [airport-editing repository](https://github.com/InfiniteFlightAirportEditing/Airports) was archived October 1, 2021. Its layouts cannot prove current spawn availability. The official API playground at commit `887611bd013a3c841cc3026a462de13329b9bfeb` exposes airport directory and airport/status operations, but the inspected endpoint catalog does not establish a current selectable-stand inventory. [Source](https://github.com/infiniteflight/infiniteflight-api-playground/blob/887611bd013a3c841cc3026a462de13329b9bfeb/src/playgroundApp.js). No API sign-in or authorization change was performed.

Current [Infinite Flight developer guidance](https://www.infiniteflight.com/guide/developer-reference) restricts Live API data to temporary caching, prohibits persistence, and prohibits AI-model training. Therefore do not put Live API responses into durable flight snapshots or saved evidence. Retention must be source-specific. A user-observed simulator gate mapping needs its own provenance/version and must not be mislabeled as a permanently licensed API dataset. No authenticated Live API call was made.

First acceptance: one dated official gate observation and a demonstrated matching selectable Infinite Flight stand, or an explicit user-visible mapping gap. A terminal or airline concourse alone is insufficient to claim an assigned gate. Occupancy is an additional dynamic fact, not implied by a valid stand name.

## Thrust: United A321neo profile

Pratt & Whitney's [June 18, 2023 announcement](https://app.prattwhitney.com/2023-06-18-United-Airlines-Selects-Pratt-Whitney-GTF-TM-Engines-to-Power-120-Airbus-A321neo-and-A321XLR-Aircraft) identifies United's engine selection as GTF for 70 A321neo and 50 A321XLR orders. This directs the profile investigation toward PW, not the previously inspected A320neo LEAP implementation. It does not identify Infinite Flight's exact rating, SimBrief custom-airframe mapping, or the represented engine software standard. Confirm those before numerical work. A newer XLR/Advantage announcement is not a reason to substitute that engine for the selected ordinary A321neo.

Required evidence, in order:
1. Current Infinite Flight United A321neo engine indication and model identity; establish whether native PERF/FLEX behavior already supplies a usable target.
2. A matching A21N SimBrief response with runway analysis, exact engine/rating, weights, conditions, configuration, thrust mode, assumed temperature, and messages.
3. An applicable PW reference that supplies the target for those conditions, with source revision and supported limits. No generic percentage or LEAP table substitution.
4. A reproducible reference case, then confirmation that the target can be read/set in Infinite Flight. Displayed N1 and equivalent physical performance remain separate claims.

Airbus's [thrust-setting article](https://safetyfirst.airbus.com/engine-thrust-management-thrust-setting-at-takeoff/?airbus-iframe=true&airbus-post=2116) explains engine stabilization before takeoff thrust and states that stabilization indications are engine-specific. This supports sourcing procedures per engine. It is not a current United PW rating table and does not supply our final N1 target. Do not copy numeric values for a different engine from its examples.

Until these requirements are met, the response must say TAKEOFF THRUST: unavailable, followed by the exact missing reference or input. Preserve any SimBrief mode/FLEX/speed values as observed data; do not present them as a resolved engine target. Zero aircraft remain verified.

## Free-first technology selection

The new mandatory technology-selection policy applies before adopting services or dependencies. No new model, dependency, SDK, or provider was installed or selected in this investigation. Earlier vendor shortlists are candidates, not provenance approvals.

Avinor remains a useful regional free-data candidate: its [official ownership statement](https://om.avinor.no/en/about-us/concern/ownership-and-management/) identifies full Norwegian state ownership and Oslo headquarters. This resolves its direct vendor ownership question; it does not establish Dulles/Newark coverage or endorse all dependencies in an eventual integration. The existing Oslo feed observation remains useful for parser development, not this US flight's gate.

## Delivery boundary

The next build should add source-aware flight observations and gate evidence to the existing MCP service, retaining missing/conflicting fields and source-specific expiry. A network provider should be added only after its actual access, reuse terms, and required provenance are established. No empty provider implementation should be described as flight research. The PW thrust profile stays in research until it has an applicable numerical method.

These are bounded work items in the backlog. Completion requires observable outputs for this chosen flight, not additional vendor lists or a plausible-looking briefing.
