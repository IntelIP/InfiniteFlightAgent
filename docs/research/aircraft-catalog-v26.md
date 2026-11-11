# Official fleet and v26 capability snapshot

Research snapshot: November 11, 2026 UTC. Owning task: [INT-409](https://linear.app/intelip/issue/INT-409).
The [machine-readable matrix](evidence/aircraft-catalog-v26.json) contains every source
airframe, listed powerplants, profile candidate, native-system evidence, change references
and unresolved fields. It is research data, not runtime dispatch configuration.

## Question

Which aircraft are in the current official fleet, what changed during v26, and what
identities/native capabilities must be resolved before expanding thrust guidance?

## Decision informed

Freeze the coverage denominator and prioritize profile-specific reference and simulator
work for v0.4.5 and v0.5. Preserve the support definition in
[goal.md](../goal.md#what-counts-as-aircraft-support).

## Conclusion

The official fleet page contains **62 records: 51 current and 11 explicitly legacy**.
Count current airframe entries once, without counting liveries or engine variants as extra
aircraft. Strict majority is **26 of 51**. No eligible subset reduces that denominator;
no entry is declared non-applicable without a profile-specific finding. Verified support
remains **0 of 51**. The existing three estimate entries remain unverified estimates.

The official production baseline is **26.5.2, build 20344**, dated November 6. This is a
release listing, not an observation of the owner's installed application or OTA content.
The matrix separates app builds, OTA packages and pre-release explanatory documentation.

## Confirmed facts

The [official fleet](https://infiniteflight.com/fleet) embeds `props.pageProps.types` with
stable airframe IDs, ICAO labels, powerplants and `legacy` flags. The site's total of 62
includes legacy records that the current fleet selector omits. All are retained in the
matrix, including repeated ICAO labels; deduplicating by ICAO would lose aircraft.

The [public SimBrief input catalog](https://www.simbrief.com/api/inputs.list.json) was read
without credentials or generation. Of the 51 current entries, 44 have a same-ICAO candidate,
two have a name-based candidate, and five lack a same-code entry. Among the 46 candidates,
41 advertise `tlr_data=true` and five advertise false. These flags describe catalog data,
not retrieved performance outputs, exact engine applicability or feasible flight plans.

Important mapping limits are retained in each row:

| Official airframe | Catalog finding | Remaining identity check |
| --- | --- | --- |
| Challenger 350 / CL35 | Honeywell HTF7350; CL35 candidate with runway-data flag | Exact simulator rating, native target and usable numerical method |
| A320neo / A20N | LEAP/PW families; standard A20N candidate | Per-livery engine/rating and selected airframe configuration |
| A320neo ACJ 1 / ACJ 2 | Official 26.5 livery listing | No tank, payload, range or VIP configuration equivalence established |
| 777F | Fleet ICAO is B77L, shared with 777-200LR; named catalog freighter is B77F | Resolve the mismatch instead of choosing the passenger entry by code |
| E175 | Fleet E75L; catalog E175 | Confirm variant and engine equivalence |
| TBM-930 | Fleet TBM9; catalog name TBM 900 | Confirm 930 configuration rather than accepting a same-code match |
| C-130J / C-130J-30 | Shared C30J catalog candidate | Distinguish short/stretched configuration and performance availability |

The [production changelog](https://www.infiniteflight.com/changelog) records v26 aircraft
additions, navigation, fuel and SimBrief integration changes. The matrix indexes the full
26.1–26.5.2 sequence and the dated OTA records returned with that page. Cosmetic updates
and added liveries do not establish a thrust-model change.

The [official cockpit overview](https://infiniteflight.com/blog/a-fresh-look-and-more-to-explore-in-the-flight-deck)
distinguishes shading work from systems work. Its more specific systems list identifies
19 current rows with a documented retrofit; the A321neo has separate documented MCDU
evidence. For the other 31 current rows, exact per-airframe native FMS capability remains
unresolved in this snapshot. Broad family language in release notes is retained separately
rather than promoted into an observed PERF function for every variant.

## Inference

`target_investigation_candidates` is engineering triage from the listed engine class:
N1/EPR for relevant jets, torque/propeller RPM for turboprops, and RPM/manifold pressure for
piston aircraft. It does not establish which indication the simulator displays. Every
`displayed_target_type` is explicitly unresolved because no current-build simulator
inspection occurred. A universal N1 formula is therefore neither assumed nor enabled.

Prioritize the source-confirmed business jet and neo configurations, then recent systems
retrofits and the existing neo/MAX estimate paths. This ordering is a research recommendation;
it does not establish an aircraft's thrust support or change release scope.

## Conflicts and unknowns

- Listed engine families are official metadata, not proof of exact simulator ratings or
  per-livery engine selection. Rating-level fields remain unresolved.
- Fleet `packageReleaseDate` metadata can predate the dated release introducing an aircraft.
  Use dated release/change records for this matrix; do not rank recency from that field.
- A documented working FMS does not prove native numerical FLEX/ATM-to-thrust calculation.
  Native PERF outputs, target types/units and usable control behavior still require inspection.
- No custom SimBrief airframes, performance calculations or account-specific profiles were
  inspected. No same-code entry does not prove that an appropriate custom profile is absent.
- Legacy records are excluded from current-fleet claims, not silently removed. No absent
  business-jet model is added by analogy with Challenger 350 or with real-world catalogs.
- Official/public access is distinct from open-data licensing. No open redistribution
  license was established for these web/API sources. Only selected factual metadata and
  original applicability assessments are committed; source pages/images/charts are not.

## Implications

Later aircraft tasks can use stable airframe IDs and source-backed change references without
mistaking a livery, cockpit facelift or catalog flag for support. Record subsequent native
observations with simulator build, installed content, livery/engine and source identity.
Numerical reference and in-simulator acceptance remain separate work in their owning tasks.

No browser, paid provider request, simulator session, model call or account change was used
for this catalog assessment. Original public responses are retained in Git-ignored
`artifacts/private/int409/`; the matrix records retrieval times and SHA-256 identities.

## Sources and validation

The matrix's source registry gives exact retrieval times, URLs, access/license limits and
response hashes for the official fleet, production changelog, cockpit overview and public
SimBrief catalog. Beta app records are not used as production findings.

Run the offline inventory check with:

```bash
python scripts/validate_aircraft_catalog.py
```

It checks denominator arithmetic, retained legacy rows, unique airframe IDs, evidence
references, app/OTA separation and unsupported verification claims. Focused corruption
tests in `tests/test_aircraft_catalog.py` exercise those failure conditions. The check
establishes internal consistency of this frozen research artifact, not aircraft accuracy.
