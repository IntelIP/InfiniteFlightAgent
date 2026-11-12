# v0.4.5 simulator observations still required

This checklist supplies the missing observations for INT-412–414. It does not report a
completed simulator test. The candidate software/evaluation results are in the
[compatibility assessment](../research/v045-thrust-compatibility.md).

## First pass: inspect native behavior

Use the owner's installed Infinite Flight build. Record the actual version/build and any
visible installed-content revision; the published 26.5.2/20344 baseline does not identify
an installed device. An unavailable field stays `unknown`.

Start with these existing profiles, before attempting any new aircraft expansion:

| Task | Aircraft/profile | First observation |
| --- | --- | --- |
| INT-412 | A320neo LEAP and PW selections actually available in the installed simulator | Exact livery, displayed engine identity, native PERF page and engine target indications |
| INT-413 | A321neo United selection, then any distinct selected LEAP/PW profile | Same identity/PERF checks; do not infer simulator engine rating from the real United tail |
| INT-414 | 737 MAX 8 selection | Displayed engine identity, native takeoff/derate/assumed-temperature controls and N1 indication |

For each selection:

1. Record the aircraft, livery and any displayed engine/rating identifier. If only an engine
   family is visible, retain that family and leave the exact rating unknown. Do not select
   a numerical model by a guessed suffix.
2. Inspect the native PERF/FMS and engine display. Record whether there are editable
   takeoff, FLEX/SEL or fixed-derate fields and whether entering them displays a numeric
   N1 target, another target kind, a mode label only, or no result. Record the displayed units.
3. Record whether native controls already provide the required actionable manual target.
   If they do, assess that path before adding or changing a dispatcher calculation.

These observations can resolve native-capability questions. They do not by themselves
establish an independent engine N1 schedule, a verified operating envelope or aircraft support.

## One matched case per observable profile

After identity/native behavior is understood, capture one matched case using an already
retained, feasible SimBrief plan if available. No new generation is required merely to
inspect a native page. A provider-generated plan remains a performance input, not an
independent reference for the dispatcher's derived N1.

Copy this record for each case; observed values must come from the named sources:

```text
Case ID:
Observed at (UTC):
Device and Infinite Flight version/build:
Installed content revision, if visible:
Aircraft and livery:
Displayed engine family/model/rating (or unknown):
SimBrief airframe/internal ID and reported engine:
Retained trip/leg/revision and OFP snapshot hash:
Runway and elevation:
Weight and units:
OAT and units:
QNH/altimeter and units:
Wind, bleed/packs and engine/wing anti-ice settings:
Native thrust mode:
Native FLEX/SEL temperature, if applicable:
Native fixed derate, if applicable:
Native target kind, value and units (or unavailable):
Observed full-rated N1, mode and conditions (if measured):
Observed response after selecting the proposed mode/target:
Original observation/reference location:
Fields not visible or not verified:
```

A full-throttle slider position is not automatically a full-rated TOGA/TO reference.
Record the actual native mode and displayed N1. Do not submit an estimated N1 as an observed
reading. Keep throttle position, engine indication and inferred physical thrust separate.

## Broader verification after the first matched cases

Per-profile independent reference data must establish tolerances and an applicable envelope
before accuracy is scored. Then select bounded cases for the relevant low/high pressure
altitude, cold/hot OAT, mass, thrust modes and bleed/anti-ice configurations. There is no
preselected numerical accuracy tolerance for an unverified profile. The 1e-9 tolerance in
the pinned C++ port checks is software arithmetic agreement, not simulator accuracy.

The existing software checks already cover changed calibration conditions/build/age,
invalid modes, missing performance, unknown engine suffixes and corrupted saved readings.
Repeat in-simulator measurements only where they resolve an actual applicability or
accuracy question. Do not infer PW or Boeing correctness from LEAP-1A26 source agreement.

## Access and release state

On November 11, the Mac's Xcode device inventory contained no connected devices. A bounded
read-only Windows check found no installed Infinite Flight package or running Infinite
Flight process. No simulator observation is available through those access paths; the owner
must identify another accessible device or provide actual observations. No app was installed,
launched or configured by those checks.

The earlier model rechecks returned a Subscription Sharing usage limit. On November 11,
Hudson increased the sharing cap from 10% to 100%; the configured GPT-6-Luna/low route
responded successfully at 23:31 UTC. The existing credential and billing route were reused.
The [resumed evaluation report](../evidence/v045-evaluations.md) records actual-model results.

Hudson separately approved four new sequential Browserbase sessions, capped at 180 seconds
each and 720 seconds total, and eight necessary FlightAware requests across PR/release
acceptance. This allowance does not authorize simulator observations or establish aircraft
accuracy. That browser batch completed across PR/release acceptance; it authorizes no further
session. [v0.4.5 is deployed](../evidence/v045-release.md), with the authenticated production
health check unavailable while the Realm host was disconnected. Profile support remains
0/51 verified, and INT-412–414 remain open for the observations described here.
