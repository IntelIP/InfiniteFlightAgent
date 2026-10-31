# Flight identity, schedules, and gate data

Research date: October 30, 2026. Scope: public documentation comparison for DISC-04. No subscriptions, trials, authenticated provider calls, or paid queries were made. Recommendations are provisional until representative data checks.

## Question and decision informed

Where can we obtain current, historical, and future flights and gate assignments for personal Infinite Flight preparation, at acceptable cost and with usable retention rights?

## Conclusion

Following Hudson's free-first direction, start with accessible airline/airport sources, permitted open data, and existing/free structured access. The [free-first strategy](free-first-strategy.md) supersedes the original paid-provider evaluation order. Keep **FlightAware AeroAPI and AeroDataBox** as structured fallback candidates and **Cirium/OAG** as broader commercial alternatives. Validate flight discovery and dated gate coverage at airports Hudson actually uses. Future schedule availability is not a guarantee of a future assigned gate.

## Confirmed facts: candidates

| Provider | Present and gates | Past | Future | Access and implication |
| --- | --- | --- | --- | --- |
| FlightAware AeroAPI | Current status; official product comparison lists actual gate/terminal data | Current product page advertises data since January 2011; historical endpoints require Standard or Premium | Dedicated schedules endpoint; staff describe up to one year published airline schedules | Personal: no monthly minimum, usage fees and stated free credit; Standard: $100/month minimum; Premium: $1,000/month. Prefer Personal evaluation for current flights, not a claim that deep history is free. |
| AeroDataBox | OpenAPI has nullable departure/arrival gate and terminal; per-movement quality flags | Direct Starter advertises up to 180 days, Growth/Scale up to 365, subject to coverage | Direct Starter up to 180 days, Growth/Scale up to 365, subject to coverage | Cost/coverage vary by direct versus marketplace plan. Useful lower-entry candidate; inspect exact plan rather than combining marketplace price with direct-plan features. |
| Cirium | Flight status documentation includes terminal/gate and scheduled/estimated/actual times | Historical status documentation advertises February 7, 2006 onward; Contract plan | Schedules API supports flight/route/airport queries; data overview says 11 months ahead | Serious historical option; price/access require plan-specific confirmation. No purchase recommendation from public docs alone. |
| OAG | Flight Info API `Content=Status` adds gate/terminal/status fields | Historical products exist; exact entitlement/horizon needs confirmation | Separate forward schedule data | Status product describes 48 hours before departure through 24 hours after arrival. Schedule and status layers must be joined; null status on future flights is expected. |
| Aviationstack | Provider FAQ lists terminal/gate when available | FAQ describes rolling three-month history | FAQ advertises future flights up to 12 months, Basic and above | Secondary candidate. Documentation redirected to an inaccessible page during retrieval; detailed endpoint/plan verification still needed. |

Primary sources for the table:

- FlightAware: [current AeroAPI product/pricing](https://www.flightaware.com/commercial/aeroapi/), [data-type comparison](https://www.flightaware.com/commercial/data), [staff explanation of the active versus future-schedule window](https://discussions.flightaware.com/t/2-days-in-future-limitation/92358).
- AeroDataBox: [OpenAPI v1.15.4.0](https://doc.aerodatabox.com/docs/openapi-direct-v1.json), [pricing and retention](https://aerodatabox.com/pricing).
- Cirium: [current status description](https://developer.flightstats.com/api-docs/flightstatus/v2/airport), [historical status](https://developer.cirium.com/apis/cirium-sky-api/historical-flight-status), [schedules](https://developer.cirium.com/apis/cirium-sky-api/schedules), [data overview](https://developer.cirium.com/apis/data/overview).
- OAG: [status data](https://www.oag.com/flight-status-data), [current API migration and field mapping](https://knowledge.oag.com/docs/flight-info-api-migration-fvxml), [joining schedules/status](https://knowledge.oag.com/linking-schedules-and-status-data).
- Aviationstack: [FAQ](https://aviationstack.com/faq).

FlightAware's older general data comparison mentions a two-week historical limit while the current AeroAPI page advertises 2011 onward and tiered access. Do not apply old product limits to new history endpoints or ignore their pricing gate. Confirm active/recent windows through the current account documentation before implementation.

## AeroDataBox schema and cost detail

Observed public schema version: **1.15.4.0**. It provides flight lookup by flight number/callsign/registration/Mode-S, single local date or date range, airport departures/arrivals, and coverage-feed endpoints. The airport movement object includes `scheduledTime`, `revisedTime`, `runwayTime`, nullable `gate`, `terminal`, and `quality` flags `Basic`, `Live`, or `Approximate`. Do not interpret a non-null field as independently verified real time. [OpenAPI](https://doc.aerodatabox.com/docs/openapi-direct-v1.json).

The pricing page lists API.Market entry pricing of $7.50/month, RapidAPI $8/month, and direct Starter $19/month. API units are not requests. The same page contains a stale “coming soon” label for direct access while its FAQ says direct subscriptions are available. Confirm availability in the selected channel. Standard raw-data retention is generally seven days, with plan-specific extensions and stated exemptions. Permanent raw response storage cannot be assumed; a private-user log exemption is not blanket raw-payload retention. [Pricing/FAQ](https://aerodatabox.com/pricing).

## Recommended source flow: inference

1. Discover flight candidates from route/airport schedules using explicit intended date and aircraft preference. Expand codeshares to the operating flight; preserve both identities.
2. Resolve operating carrier, flight number, departure local date, route, segment, provider ID, and scheduled UTC/local time.
3. For a past flight, query historical operational data rather than today's flight with the same number. For future flights, retain schedule-only status until actual assignment data appears.
4. Retrieve assigned gate/terminal near departure when available. An older gate from a previous occurrence is historical context, not a future assignment.
5. Cross-check airline/airport sources when necessary and accessible. Use bounded web research with source/date attribution; search snippets do not establish current assignment.
6. Map the reported gate to an actual Infinite Flight position using a distinct simulator-airport reference. Recheck suitability and occupancy/reservation where exposed. A provider's gate string does not prove a selectable or free simulator stand.
7. For private flights, research FBO/handling facilities and suitable simulator ramps. Do not infer FBO assignment from ADS-B position or fabricate a scheduled airline flight number.

Do not buy an aircraft-position feed expecting airline gate data. Position tracking, schedules, status, and stand assignment are different products. Flightradar24/OpenSky may help tracking, but this review did not establish them as complete gate/schedule sources for our requirement.

## Evaluation plan and decision gate

One bounded evaluation should include a current airline departure from KIAD, a short-past occurrence of that flight, a much older flight, a future flight next week and several months ahead, a European airport, a codeshare, and a private-FBO scenario. Record exact dates/IDs; flight discovery success; gate null/non-null; assignment observation time; carrier/aircraft completeness; fetch cost; and actual simulator mapping. Include at least one unavailable-gate case.

First evaluate the free-source path in the [source strategy](free-first-strategy.md). Compare structured free allowances or paid candidates only against demonstrated coverage/maintenance gaps. A $100/month historical AeroAPI tier is an exceptional proposal requiring a concrete benefit and approval; it is not a baseline dependency. Cirium/OAG remain alternatives if requirements justify contracting.

## Conflicts and unknowns

No named-flight live gate response, current KIAD-to-simulator stand mapping, per-airport fill rate, historical gate-change history, subscription entitlement, or cost-per-completed-dispatch was measured. Real-time marketing does not establish zero latency. An API may return the final historical gate without its full assignment timeline. Distant future gates may be unassigned, provisional, or absent regardless of schedule horizon.

Some Cirium pages were search-index readable but later opened as dynamic shells. FlightAware's interactive developer portal was inaccessible. These limits prevent claiming detailed authenticated schemas and entitlements. Prices are public snapshots, not quotes or approved spending.

## Implications

DISC-04 has a documented shortlist and sample plan, but its grounded gate-to-spawn acceptance remains blocked. Shared data contracts need separate temporal class (`historical`, `current`, `future_schedule`), scheduled/estimated/actual time, gate evidence status, provider provenance, and retention/expiry policy. Preserve raw evidence only within the selected provider's permitted scope; retain a source reference and non-sensitive audit metadata where storage is restricted.
