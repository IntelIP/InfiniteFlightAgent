# Aircraft coverage

Status: planning; **zero aircraft have verified thrust-translation support in this project**. This describes available evidence, not a change to launch scope. The support definition is owned by [goal.md](goal.md#what-counts-as-aircraft-support).

## Current fleet baseline

The [November 11 v26 catalog assessment](research/aircraft-catalog-v26.md) freezes the
official inventory and capability/change matrix: **51 current airframe entries, 11 legacy
records retained separately, strict majority 26, verified support 0**. It records official
powerplant labels, SimBrief candidates, native-system documentation and explicit unknowns.
The published simulator baseline is 26.5.2 build 20344; no current-build simulator inspection
was performed for this inventory. The dated launch research below remains historical.

## v0.4.5 compatibility corrections

The [compatibility assessment](research/v045-thrust-compatibility.md) records exact
engine matching, condition validation, calibration scope and retained-source corrections.
Software checks and pinned simulation-source agreement are separate from aircraft verification.
The [release and exact-image acceptance](evidence/v045-release.md) are recorded. Independent
profile references and current-build simulator observations remain open; this patch establishes
no new aircraft support. INT-412–414 retain those verification requirements.

## Launch register

| Candidate profile | Infinite Flight / SimBrief identity | Engine family | Method and support | Verification |
| --- | --- | --- | --- | --- |
| A320neo LEAP | A20N; A320-251N = LEAP-1A26 (EASA A.064) | LEAP-1A | Researching; FlyByWire simulation table consistent with LEAP-1A26 rating, provenance unverified | Blocked |
| A320neo PW | A20N; A320-271N = PW1127G-JM (EASA A.064) | PW1100G-JM | No public N1 method found | Blocked |
| A321neo LEAP | A21N; A321-251N/-253N = LEAP-1A32/-1A33/-1A35A (EASA A.064) | LEAP-1A | No public N1 method found | Blocked |
| A321neo PW | A21N; A321-271N(X) = PW1133G(A)-JM; United N14507 = PW1133G-JM (FAA registry) | PW1100G-JM | No public N1 method found; D-09 decision needed | Blocked |
| A320 ceo scope question | A320-200 / A320 | CFM56-5B or IAE V2500 | Initial inclusion awaits clarification; no verified method | Not run |

Outside launch scope, the B38M (737 MAX 8, LEAP-1B28) also has a labeled estimate path in `estimate_takeoff_n1` (Hudson request, October 30, 2026); it is not supported under the criterion below.

These are engine-family candidates, not confirmed rating-level profiles. Official fleet and A321neo livery-policy sources are recorded in the [focused follow-up](research/launch-dependencies-followup.md#confirmed-facts-launch-aircraft-and-native-capabilities). A321neo engine selection follows the airline/livery. Certified model mapping and source inventory: [thrust source inventory](research/thrust-source-inventory.md). Infinite Flight's per-livery representation remains DISC-01 work; ceo inclusion remains a user scope decision.

Public SimBrief entries A320/A20N/A321/A21N advertise runway-analysis support, which does not establish matching engine ratings or final targets. See [catalog evidence](research/evidence/simbrief-aircraft-extract.json) and [professional-source assessment](research/professional-thrust-sources.md).

## Status meanings

- **Unassessed:** identity or translation path has not been investigated.
- **Researching:** a focused investigation is underway.
- **Provisional:** an applicable method is proposed; required verification remains incomplete.
- **Supported:** the aircraft's documented translation acceptance and required verification pass within stated conditions.
- **Unsupported:** needed data/method is absent or incompatible; record the exact limitation.
- **Not applicable:** the takeoff-performance/target workflow does not apply; explain why and exclude it transparently from any coverage metric.

Verification outcomes remain `passed`, `failed`, or `blocked`; coverage status is not a substitute for those outcomes.

## Required profile information

For each aircraft, record simulator identity/version, SimBrief airframe and engine/rating, supported thrust modes, input units, target indication/units, source and resolution method, supported conditions, required user guidance, optional throttle-position calibration, and verification evidence tied to the relevant profile/application revision.

The verification case must establish that the method applies to that aircraft and that the instruction is usable in Infinite Flight. Displayed engine indication, throttle slider percentage, and equivalent physical thrust/performance are separate claims; only claim the layer tested. Simulator updates require an impact check before assuming older calibration remains valid.

## Expansion selection

After launch, refresh the official fleet and update history, rank recent aircraft updates first, then group compatible candidates into manageable batches. Keep out-of-scope and unsupported aircraft visible. Broad-coverage reporting must name the fleet snapshot, denominator, exclusions, and count supported by the definition above.
