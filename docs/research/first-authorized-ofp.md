# First authorized SimBrief OFP observation

Research date: October 30, 2026. DISC-06 evidence. One user-requested latest-plan fetch succeeded using the supplied Alias, an identifying client, and `json=v2`. No dispatch was generated or changed.

## Question and decision informed

Does the actual latest OFP include structured takeoff performance and a usable engine target? This determines the parser requirements and whether a separate target resolver is necessary for this observed profile.

## Confirmed facts

The retrieved plan was generated October 29, 2026 at 00:15:52 UTC: KIAD → KEWR, B737 MAX 8 (`B38M`), engine `LEAP-1B28`, AIRAC 2503, weight unit `kgs`. It is not a launch neo sample and is not current-weather guidance.

`tlr.takeoff` contains a `conditions` object and a `runway` array with eight results. The planned runway is 30; select by identifier rather than array order. For that runway, the stored result contains flaps 5, D-TO2, assumed temperature 48, bleeds ON, anti-ice OFF, V1/VR/V2 137/137/145. These are observations of a saved simulation plan, not a newly calculated thrust instruction. They differ from the earlier pasted example; never mix conditions or outputs across revisions.

All eight runway entries have `thrust_value: []` and `thrust_value_id: []`. This response therefore supplies neither a numeric engine target nor its indication identifier in those fields. It does not prove these fields are always empty for other aircraft, modes, or plans.

The top-level takeoff members are nested objects/arrays. The inspected upstream `get_performance` implementation skips nested values, so it would omit this observed takeoff structure. Preserve the raw payload and parse the selected runway explicitly. Numeric-looking fields arrive as strings; empty arrays and empty strings also occur. Do not coerce missing targets to zero.

## Evidence

[Sanitized takeoff extract](evidence/simbrief-b38m-takeoff-observation.json) preserves the observed takeoff structure, engine identity, source timestamp, and SHA-256 of the original response. The complete original response is stored only in Git-ignored `artifacts/private/latest-ofp.json` with owner-only file permissions. Account identifiers and plan-download URLs are excluded from the sanitized extract. The user's email and account profile are not needed for this integration.

Official contract: [Navigraph latest-OFP retrieval guidance](https://forum.navigraph.com/t/fetching-a-users-latest-ofp-data/5297).

## Inference and unknowns

This observation validates retrieval and the nested-runway parser requirement for one B38M response. It provides a useful missing-target fixture. It does not establish authenticated generation, multi-leg retention, neo performance shape, professional N1 calculation, or Infinite Flight import/engine behavior.

## Next evidence

Generate an A320neo or A321neo plan with takeoff performance in SimBrief, then request another latest-plan inspection and specify the Infinite Flight aircraft/livery. Do not poll for this change. No launch coverage status changes on the strength of the B38M observation.
