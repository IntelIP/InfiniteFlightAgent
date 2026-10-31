# Free-first source and operating strategy

Updated October 30, 2026 following Hudson's direction to prioritize free/open-source technologies and reduce cost and operations. Accepted preference is owned by [goal.md](../goal.md#cost-and-operations-preference--accepted-october-30-2026). This document proposes how to apply it; no services or accounts were configured.

## Question and decision informed

How should we reorder research and source selection to minimize recurring cost and operational work while preserving reliable flight preparation and aircraft-specific thrust translation?

## Conclusion

Evaluate existing access, free public sources, and appropriate open-source components first. Keep professional paid products as reference/access alternatives when a specific gap cannot be met. Neither an open-source client nor a free website makes its underlying data freely licensed, complete, or professionally validated. Prefer a simple supported integration over a brittle scraper or a self-hosted service that costs more time to maintain.

## Proposed source order

| Capability | First option to assess | Limits and escalation |
| --- | --- | --- |
| Dispatch and runway analysis | Existing SimBrief account and approved integration; reuse MIT MCP code | SimBrief is a service, not an open-source performance database. Generation access and final N1 remain unresolved. |
| Airport/runway identity | OurAirports public-domain CSVs, small local cache | Community airport facts, not assigned gates, current certified obstacle analysis, or simulator stand inventory. |
| Weather | NOAA Aviation Weather Center's public METAR/TAF API; reuse applicable weather already in the OFP | Cache and respect limits. Forecast horizons and historical availability differ; do not treat forecasts as actual future conditions. |
| Flight identity, schedule, gate | Accessible first-party airline/airport public information, with dated provenance and bounded research | Free to view does not establish bulk/API/reuse rights. Dynamic pages, coverage, past records, and future assignments can be missing. Validate representative cases before selecting automation. |
| Structured operational data | Existing access or a genuinely sustainable free allowance, only if terms and billing controls fit | No paid account, trial signup, feeder hardware, or overage billing is authorized. Trials are evaluation tools, not a permanent foundation. |
| Historical/future coverage | Public records and permitted reusable data where available; explicitly record unmet date/gate coverage | Do not replace a dated flight's gate with another occurrence. Paid providers become a proposed exception only for demonstrated gaps. |
| Simulator parking | Verified local airport/stand mappings for the airports used, enriched from permitted scenery/reference data | Mapping and maintenance are real work. A real gate label does not prove current stand availability. |
| Thrust translation | Inspect raw SimBrief results, current openly accessible technical material, and engine-specific open-source implementations | Verify source provenance, license, exact applicability, and the professional-standard requirement. A simulator model is not automatically OEM data or valid for Infinite Flight. |
| Runtime and storage | Deep Agents plus ordinary tools, local process and local storage as proposed | Hosting needed for some clients remains a decision. Local runtime still incurs model/search costs if those services are used. |

## Confirmed free/open source candidates

- **OurAirports:** nightly airport/runway/navaid downloads are public domain, without accuracy guarantees. This supplies inexpensive base reference data, not gates or flight schedules. [Official data page](https://ourairports.com/data/).
- **Aviation Weather Center:** public machine-to-machine weather API includes METAR/TAF; documentation describes up to the previous 30 days in its database. Verify endpoint-specific access and limits before use. [Official API](https://aviationweather.gov/data/api/).
- **FlyByWire:** aircraft source code is published under GPLv3 with file-specific exceptions. Its engine/thrust implementation is worth a scoped inspection for the matching engine/rating, provenance, and applicability. No code has been incorporated and no method is accepted as professionally validated. [Official licenses](https://www.flybywiresim.com/licenses/), [systems API](https://docs.flybywiresim.com/aircraft/a32nx/a32nx-api/a32nx-systems-api/).
- **Existing SimBrief MCP:** MIT source can reduce integration work; source findings and pinned revision remain in [the extension report](simbrief-extension.md).
- **OpenSky:** official FAQ says it does not map tracking data to commercial schedules; continued operational users must contact it for licensing. It is not our default free gate/schedule source. [Official FAQ](https://opensky-network.org/about/faq).

## Thrust research order under the new preference

1. Establish exact launch aircraft/engine/rating identity and inspect authorized raw SimBrief data.
2. Inspect openly accessible, applicable technical references and engine-specific open-source methods for a defensible target-resolution path. Identify whether data is measured, modeled, OEM-derived, or unknown; check versions and license before reuse.
3. Compare any candidate against an applicable professional reference or authorized reference result and relevant simulator observations. Do not invent a conversion or call a simulator model professionally validated because its source is visible.
4. If the required source quality cannot be established freely, document the precise missing input/reference and propose the smallest professional-access exception. Paid OEM products are no longer the default starting integration.

The requested source standard and free-first preference may create a genuine access gap. Bring that tradeoff to Hudson with evidence rather than silently weakening support criteria or purchasing access.

## Evaluation and operational cost

DISC-08 should first try a small airline/airport sample using accessible free sources: current departure, past occurrence, future schedule, missing gate, and one simulator stand mapping. Record which capabilities fail and why. Evaluate a structured free allowance only where it reduces operational effort, checking expiry/overage risks before account setup.

Use on-demand requests rather than continuous polling. Cache static facts separately from changing assignments and only for permitted durations. Reuse one identified plan snapshot across tools. Store already-established aircraft methods so the model does not research them again for every flight. Keep both original source identity and freshness visible.

Measure the cost of a complete dispatch: model calls, search/provider charges, hosting, setup, manual recovery, and maintenance. Do not replace a paid API with an unmaintainable scraping system to claim lower cost.

## Unknowns and implications

No globally complete, free historical/current/future gate source or professionally validated free neo-thrust resolver has been established. Requirements remain; coverage gaps are explicit. Existing paid comparisons remain useful as fallback evidence, not purchase recommendations. Reorder DISC-07 and DISC-08 accordingly. No new provider selection, software installation, hosted service, or spending was performed.
