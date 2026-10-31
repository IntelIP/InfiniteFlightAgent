# Professional takeoff thrust sources and translation plan

Research date: October 30, 2026. Scope: DISC-02 and prerequisites from DISC-01. Public first-party/regulatory evidence, not a calculated target, simulator experiment, subscription assessment, or certification of our product.

## Question and decision informed

Which current professional systems or aircraft data can turn a SimBrief takeoff solution into the launch aircraft's manual engine target? What additional evidence and access are required?

## Conclusion

There is **no verified public, professional A320neo/A321neo FLEX-to-N1 API available to this project** from this investigation. This is an access/capability gap, not evidence that none exists. Following Hudson's free-first direction, inspect freely accessible applicable engine-rating references and engine-specific open-source methods first, with explicit provenance and professional-reference validation. The [free-first strategy](free-first-strategy.md) owns the revised evaluation order. Airbus **Mission+ PERFO** and other professional vendors remain potential reference/access exceptions if the necessary standard cannot be met freely. Do not replace the gap with an LLM estimate, a community percentage, or an unrelated calculator's results.

Keep SimBrief as the dispatch/performance source. If a professional source recomputes performance, require matching conditions and a coherent solution; do not silently combine one source's FLEX/V-speeds with another source's incompatible N1 or thrust mode. A disagreement is a reconciliation task.

## Confirmed facts: SimBrief and aircraft metadata

- SimBrief staff say OFP runway-analysis results are available in XML/JSON when enabled. In May 2024 they described a standalone performance API as a possible future feature; August 2026 follow-ups do not establish a released API. [Official support thread](https://forum.navigraph.com/t/takeoff-performance-api/15840).
- In July 2025, SimBrief staff explained in an Avro RJ discussion that SimBrief did not know/display actual N1 and expected aircraft systems or tables to supply it. This is relevant negative evidence, not a current universal schema guarantee for all aircraft. Inspect current launch-aircraft raw data once authorized. [Staff explanation](https://forum.navigraph.com/t/avro-rj-derated-takeoffs/20092).
- The public SimBrief aircraft list was fetched successfully during this investigation. Entries A320, A20N, A321, and A21N report `tlr_data=true`. A20N/A21N list `accuracy=fair`, while A320/A321 list `accuracy=high`; these are SimBrief metadata labels, not professional certification or a measured error bound. Engine/rating was not included in these entries. [Public JSON](https://www.simbrief.com/api/inputs.list.json), [list documentation](https://developers.navigraph.com/docs/simbrief/layout-options). Selected original entries are retained in [the public metadata extract](evidence/simbrief-aircraft-extract.json).
- Official Infinite Flight release notes list A320neo in 26.5 (October 29, 2026) and describe both A321neo engine variants in update history. This does not establish exact engine ratings, FADEC logic, or family interchangeability. [Official changelog](https://www.infiniteflight.com/changelog).

## Confirmed facts: professional systems

| System/source | What first-party evidence establishes | What it does not establish for us |
| --- | --- | --- |
| Airbus Mission+ PERFO | Current OEM performance/weight-and-balance solution, replacing Flysmart+ progressively; cloud-hosted iOS; Airbus SOP integration; manufacturer reports FAA/EASA OSL | Personal developer eligibility, price, public API, exact neo engine/rating coverage, final N1 export, and use inside our agent are unverified |
| Airbus Flysmart+ / applicable AFM/FCOM and engine-rating data | Established professional lineage. EASA's older evaluation describes aircraft/airport/operator customization and performance databases based on AFM plus operational data | An old evaluation is not a current dataset or transferable engine table; finding an online PDF does not establish revision, applicability, or permission to integrate it |
| ForeFlight Runway Analysis | Official support explicitly includes aircraft-dependent takeoff N1/EPR output | Exact A20N/A21N coverage, selected FLEX compatibility, integration access, and price remain unverified |
| APG Genesis PRO / supported list | Professional runway-analysis product with engine-specific public coverage and optional coverage-query access | Inspected Airbus rows list ceo CFM56/IAE combinations; no neo configuration was established. Coverage-query access is not a calculation API entitlement |
| Flygprestanda Guru2 / runway charts | Vendor describes AFM/SCAP-based analysis and lists A320/A321 families | Family names alone do not confirm LEAP/PW neo rating coverage, final N1 export, API access, or personal pricing |
| Boeing OPT | Current 2026 OEM material describes takeoff/landing and weight/balance calculations using Boeing SCAP data | Relevant to later Boeing batches, not a substitute for Airbus engine data |

Sources:

- [Airbus Mission+ PERFO](https://www.skywise.com/en/digital-solutions/flight-operations/mission/mission-perfo).
- [EASA FlySmart evaluation](https://www.easa.europa.eu/sites/default/files/dfu/certification-experts-docs-oeb-reports-airbus-Fly-Smart-with-Airbus-for-iPad---EFB-Software---Final-signed.pdf), an older evaluation used for lineage and architecture only.
- [ForeFlight output definitions](https://www.foreflight.com/support/runway-analysis/).
- [APG engine-specific coverage](https://flyapg.com/products/supported-aircraft).
- [Flygprestanda runway analysis](https://www.flygp.se/products/runway-analysis-charts.html), [supported families](https://www.flygp.se/supported-aircraft.html).
- [Boeing OPT 2026 product sheet](https://services.boeing.com/bgsmedias/sys_master/root/h65/ha3/9119299239966/Onboard-Performance-Tool-Digital-Services-2026/Onboard-Performance-Tool-Digital-Services-2026.pdf).

## Simulator methods are a separate evidence class

Follow-up source inspection found a concrete table/interpolation-based N1-limit method and its speed-dependent caller at pinned FlyByWire commit `66021c24448c44399a8ff569eb14715b6b26558e`. See [integration findings](integration-blueprint.md#concrete-open-source-thrust-finding) for the exact surfaces and missing applicability/provenance evidence. No supported target has been calculated.

FlyByWire's developer documentation describes thrust-limit and commanded-N1 interfaces for its own A32NX simulation. Its code/docs may explain a simulator implementation, but neither establishes Airbus professional-data provenance or applicability to Infinite Flight. [A32NX systems API](https://docs.flybywiresim.com/aircraft/a32nx/a32nx-api/a32nx-systems-api/), [thrust controls](https://docs.flybywiresim.com/pilots-corner/a32nx/a32nx-briefing/flight-deck/pedestal/thrust-pitch-trim/).

Community rules and simulator calculators were not promoted to professional sources. A recently published web calculator can still be an approximate model. Any future proposal to use such a model must name its provenance and limitations and obtain a product decision if it weakens the requested standard.

## Required calculation and protocol contract: proposed

The desired operation is an aircraft-specific **thrust-rating resolver**, not a universal conversion from degrees Celsius to percentage.

Input categories to establish from the selected source:

- Exact simulator aircraft, engine variant, certified rating, relevant software/profile version, and compatible SimBrief airframe.
- Thrust mode, fixed derate where applicable, selected FLEX/assumed temperature, actual temperature, pressure/altitude inputs, and relevant atmospheric/speed state.
- Bleeds/packs, anti-ice, and other configuration corrections required by that method.
- SimBrief takeoff weight, runway/configuration, speeds, and messages as the parent solution. Some are consistency context rather than direct variables in an engine-rating formula; use the source-defined dependencies.

Outputs: numeric target and indication/units; conditions under which it applies (for example static versus rolling reference if the source distinguishes them); exact mode/configuration; source and dataset revision; validity limits; and aircraft-specific manual-setting instructions. Optional slider position remains a simulator calibration, not the professional target itself.

Protocols/checklists must come from the applicable aircraft guidance. Establish any required stabilization, setting, confirmation, and thrust-reduction instructions per profile. Do not generalize a Boeing sequence to Airbus or treat a reduced thrust value as an automatic-throttle command.

## Proposed next work and release gate

1. **Identity:** enumerate exact Infinite Flight launch aircraft/engine representations and match official SimBrief profiles. Ask Hudson only about unresolved product scope, not discoverable facts.
2. **Raw solution:** inspect a user-authorized, current A20N/A21N OFP with runway analysis. Confirm fields, selected runway/configuration, modes, units, and whether explicit target values exist.
3. **Free-first method assessment, then access exception if needed:** inspect applicable open references and engine-specific source code for provenance, license, valid conditions, and professional-reference evidence. If necessary, prepare inquiries to Airbus and suitable vendors about personal simulation use; exact engine/rating coverage; consuming an existing FLEX solution versus recalculating; N1 output; update cadence; API/export; storage; and cost. Do not send inquiries without explicit authority.
4. **Worked reference:** with an authorized tool/dataset, record one reproducible case per engine/rating and then the conditions needed to establish supported operating bounds. Numerical tolerances must follow source precision and observed simulator behavior, not be invented now.
5. **Simulator compatibility:** validate that the target can be selected/read in Infinite Flight and assess materially relevant differences from the source model. A matching displayed N1 is not proof of equivalent physical thrust or runway/climb performance. Record exactly which claims pass.
6. **Release:** mark an aircraft supported only after the requested translation and guidance are verified. If professional data cannot be obtained, report the affected launch blocker and bring the tradeoff to Hudson; do not silently downgrade to assumptions.

## Conflicts and unknowns

Earlier planning left open the possibility of simply extracting hidden N1 from SimBrief. Staff evidence makes this a hypothesis to test, not a dependable architecture premise. Earlier references to Flysmart+ alone were incomplete; Mission+ PERFO is now the current OEM product to assess.

No professional subscription, current authorized engine-rating dataset, numerical A320neo/A321neo target, matching working API, exact simulator engine mapping, or simulator observation was available in this research. Accordingly DISC-02's numerical acceptance is **blocked**, not passed. No need to investigate arbitrary further calculators until the named coverage/access questions can change the decision.
