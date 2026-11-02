# Takeoff N1 source inventory: launch engines

Research date: October 30, 2026. Scope: DISC-01, DISC-07, DISC-11 and decision D-09. Hudson authorized a bounded inventory instead of a broad scrape.

Method:

- Public regulatory documents, the FAA aircraft registry, public GitHub repositories, and previously recorded professional-source findings.
- No paid access, no account changes, no leaked manufacturer manuals, and no calculation of a user-facing thrust target.
- Downloaded documents were kept outside the repository. EASA marks its TCDS copies "Copies are not controlled", so values below are cited to the named issue.

## Question and decision informed

For each launch engine, is there a usable, legitimately sourced way to turn SimBrief's FLEX/assumed temperature and conditions into a takeoff N1 target? What exactly must Hudson decide where there isn't one?

## Conclusion

The exact engines are now identified, and the public certification data anchors their ratings. **No public source provides the takeoff N1 schedule for any launch engine.** The engine data sheets say explicitly that thrust management versus speed, altitude and temperature is "defined and agreed with the aircraft type certificate holder", which is Airbus.

The only inspectable FLEX→N1 method is FlyByWire's simulation of the A320neo LEAP engine. Its configured thrust matches the LEAP-1A26 certified rating, but the source of its table values is not stated.

There is no usable source for the Pratt & Whitney engines (including United's A321neo PW1133G-JM) or for the A321neo LEAP ratings. A large-scale scrape would not change this. What remains is a source-quality decision for Hudson (D-09).

## Confirmed facts: exact engine identity

Airbus aircraft-to-engine mapping, from EASA TCDS A.064 Issue 62 (26 June 2026), Section 1 (A320) and Section 2 (A321):

| Aircraft model | Engines |
| --- | --- |
| A320-251N | CFM LEAP-1A26 |
| A320-252N / -253N | LEAP-1A24 / LEAP-1A29 |
| A320-271N | IAE PW1127G-JM |
| A320-272N / -273N | PW1124G1-JM / PW1129G-JM |
| A321-251N / -251NX | LEAP-1A32 |
| A321-252N / -252NX | LEAP-1A30 |
| A321-253N / -253NX | LEAP-1A33 (LEAP-1A35A with mod 160820) |
| A321-271N / -271NX | PW1133G-JM or PW1133GA-JM |
| A321-272N / -272NX | PW1130G-JM |

The real United A321neo observed tonight (N14507, flight UA495) is registered with the FAA as an **Airbus A321-271NX with IAE PW1133G-JM engines** ([FAA registry](https://registry.faa.gov/AircraftInquiry/Search/NNumberResult?nNumberTxt=14507), retrieved October 30, 2026). That is one aircraft. It does not establish the configuration of United's whole fleet or Infinite Flight's representation.

## Confirmed facts: certified ratings

**PW1100G-JM**, from EASA TCDS IM.E.093 Issue 14 (16 October 2026). Values are sea-level static thrust up to the flat-rating temperature:

| Engine | Take-off thrust | Flat rating | Max continuous |
| --- | --- | --- | --- |
| PW1127G-JM | 120.44 kN (27,075 lbf) | **47 °C** | 117.19 kN |
| PW1133G-JM | 147.28 kN (33,110 lbf) | **30 °C** | 145.81 kN |
| PW1130G-JM | 147.28 kN (33,110 lbf) | **30 °C** | 135.27 kN |

- The PW1127G-JM's take-off flat-rating temperature is listed as 47 °C/117 °F, and the PW1133G-JM's as 30 °C/86 °F.
- The N1 maximum is 10,047 rpm; the extracted text does not give a percentage-to-rpm definition.
- "Power setting, power checks, and control of engine thrust output in all operations are based on Low Rotor Speed (N1)."

**LEAP-1A**, from EASA TCDS E.110 Issue 14 (11 May 2026):

- Take-off thrust values in the ratings table: 10,680 / 12,064 / 13,029 / 14,305 daN.
- **LEAP-1A26 = 12,064 daN (120.64 kN ≈ 27,120 lbf).** The other column assignments were ambiguous in text extraction; check them against the PDF before relying on them.
- N1 maximum is 3,894 rpm (101 %), where 100 % N1 = 3,856 rpm.
- The flat-rating temperature does not appear in the extracted EASA text. A Japanese type data sheet shows 30 °C for a LEAP-1A row whose model wasn't confirmed.

The key limitation, from EASA E.110: "Engine models which have the same approved ratings in standard static conditions will provide different level of thrust at altitude and/or high temperature conditions. This is controlled by the engine identification plug. Power management will vary take-off and maximum continuous thrust as a function of aircraft speed, altitude, and temperature as defined and agreed with the aircraft type certificate holder."

**Regulatory bound:** FAA [AC 25-13](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC25-13.pdf) (active, 1988) requires reduced takeoff thrust of at least 75 % of the applicable takeoff thrust. This is a validity check for any FLEX result, not a source of N1.

## Inventory by source class

| Source | Engine coverage | Can it supply FLEX→N1? | Usability |
| --- | --- | --- | --- |
| EASA/FAA engine TCDS | All launch engines | No. Ratings, flat-rating temperatures and N1 limits only | Public; anchors identity and bounds |
| EASA aircraft TCDS A.064 | All A320neo-family models | No. Model-to-engine mapping | Public; resolves exact rating |
| FAA aircraft registry | Individual tail numbers | No. Engine model per aircraft | Public |
| FAA AC 25-13 | Regulatory method | No. Minimum 75 % thrust | Public |
| FlyByWire A32NX `ThrustLimits_A32NX.hpp` (GPL-3.0) | A320neo LEAP. Configured static thrust 27,120 lbf matches LEAP-1A26 (inference from the matching values) | **Yes, as a simulation**: corrected-N1 tables for TO, GA, CLB and MCT, FLEX branch, temperature-ratio conversion, bleed corrections | Inspectable and licensed. Unchanged since 2024-09-13 (`c4ab9895fb29`), identical to our pinned `66021c2`. No statement of where its data came from. Only covers LEAP-1A26 |
| FlyByWire A380X | Trent 900 | Simulation | Out of launch scope |
| Salty 747-8, Heavy Division 787 (GPL-3.0) | GEnx, Trent 1000 | Their FMC thrust-limit pages call the default MSFS FMC limit (`getThrustTakeOffLimit()`) rather than an independent engine table | Not an engine source |
| GitHub PW1100G repositories | Named "PW1100G" | Not shown | No license or verifiable owner; excluded |
| Professional tools (Mission+ PERFO, ForeFlight, APG, Flygprestanda) | Varies | Professional N1 output for some products | Paid or contract; see [professional sources](professional-thrust-sources.md) |
| Manufacturer FCOM/FPPM copies found online | Varies | Contain tables | **Excluded.** Proprietary, unverified revision and rating, intellectual-property risk |
| Community rules of thumb (IF forum guides) | A321neo | Throttle-% approximations | **Excluded** by the accepted standard |

Code search limitations: GitHub code search did not index FlyByWire's known thrust file, and repository search returned few results. Absence findings are bounded to the named sources and searches, not a proof that no source exists anywhere.

## Per-engine status

| Launch profile | Exact engine | Usable FLEX→N1 method | Status |
| --- | --- | --- | --- |
| A320neo (A320-251N) | LEAP-1A26 | FlyByWire simulation (rating consistent) | **Candidate method.** A professional reference check and in-simulator check are still required |
| A321neo LEAP (A321-251N/-253N) | LEAP-1A32/-1A33/-1A35A | None. FlyByWire's table is the LEAP-1A26 rating and must not be scaled without a method | Blocked |
| A320neo PW (A320-271N) | PW1127G-JM | None | Blocked |
| **A321neo PW, United (A321-271NX)** | **PW1133G-JM** | None | **Blocked** |
| Boeing 737 MAX 8 (later batch) | LEAP-1B28 | None independent | Not in launch scope |

## Options for Hudson (D-09)

These options are proposals; none is accepted. The current standard requires professional applicable sources.

1. **Professional access, per engine.** Ask Airbus (Mission+ PERFO) and the listed vendors about personal-simulation licensing, exact PW1133G-JM / LEAP-1A coverage, and whether they return an N1 target for a given FLEX. This meets the current standard. Contacting them needs Hudson's authorization.
2. **Accept simulation-grade methods with explicit labeling.** Use FlyByWire for LEAP-1A26. For engines with no table, build a model anchored to the certified ratings and flat-rating temperatures above, with its error unquantified until compared with a reference. The briefing would say "simulation-grade estimate." This changes the accepted standard and is Hudson's call.
3. **Simulator-referenced calibration.** Measure how Infinite Flight's own engine model responds: N1 at TOGA, and thrust versus N1 versus slider, for the chosen livery/engine. Use that as the target space. This optimizes for "what works in Infinite Flight", not real-aircraft N1, and must be labeled as such. It can be combined with option 2.

Whatever the choice, check every result against the AC 25-13 minimum and the certified rating identity. The A320neo LEAP-1A26 candidate method can be implemented and tested now without deciding D-09, as long as it stays labeled `candidate_method`.

## Proposed next work

- **Hudson:** decide D-09 for the United A321neo PW1133G-JM case: option 1, 2, 3, or a combination.
- **Can start immediately (Ralph-loop eligible):** implement `resolve_takeoff_n1` for LEAP-1A26 by porting the FlyByWire method under GPL-3.0 obligations, with pinned-commit provenance. Reproduce worked cases from the source logic and label every output `candidate_method`. Completion criterion: tests reproduce the source within its precision, and every unsupported engine returns `unsupported_profile`.
- **In the simulator, by Hudson:** the Infinite Flight PERF/E-WD/engine-variant observations listed under DISC-11.

## High-altitude extension (v0.3.0, November 2, 2026)

The estimator originally ported only FlyByWire's takeoff rows from -2,000 to 2,000 ft, so
high airports such as Denver returned "unavailable". `ThrustLimits_A32NX.hpp` at the pinned
commit (`66021c24448c`, file SHA-256 `1d9871dd…725bfd`) has 21 takeoff rows up to 16,600 ft.
All of them are now ported verbatim, together with its altitude-dependent bleed corrections
(larger at and above 8,000 ft).

What this does and doesn't establish:

- The rows are FlyByWire's LEAP-1A26 simulation, as before; their provenance is still unstated.
- The other engines' sea-level corner points are shifted with FlyByWire's corner lapse. EASA
  E.110 notes that engines with the same static rating deliver different thrust at altitude, so
  this shift is an assumption. Above 2,000 ft the corner tolerance therefore grows by 25% of
  the corner's drop from its 2,000 ft value (+/-3.2 C more at 5,456 ft). The 25% is a judgment
  that keeps the widening proportional to the extrapolation; no source quantifies it.
- On a real SimBrief A321neo plan from Denver (FLEX 47 C, OAT 11 C, 5,456 ft), the estimate is
  0.862 x full-thrust N1 (0.810-0.920) and is flagged as exceeding FAA AC 25-13's 25% reduction.
  SimBrief would not plan that, which suggests the extrapolated LEAP-1A32 corner is low
  (conservative N1) at that altitude. Calibrating the corner against SimBrief's own FLEX limits
  is a possible follow-up.
- Estimates at or below 2,000 ft are unchanged (270 combinations compared with v0.2.1).
