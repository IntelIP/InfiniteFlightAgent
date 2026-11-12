# v0.4.5 thrust compatibility candidate

Assessment dated November 11, 2026. Tasks: [INT-412](https://linear.app/intelip/issue/INT-412),
[INT-413](https://linear.app/intelip/issue/INT-413), [INT-414](https://linear.app/intelip/issue/INT-414),
[INT-415](https://linear.app/intelip/issue/INT-415). Comparison application: v0.4.4 source
`eef57bcaec856b1bd56bc9b1a1a2f992b67fb61f`. This is candidate evidence, not a release or
simulator-support declaration. Production remains v0.4.4.

## Corrections justified by observed software failures

The frozen [39-case contract matrix](../../evals/thrust_cases_v045.json) was established
before implementation. v0.4.4 passes 20/39; the candidate passes 39/39. The old estimator
accepted unknown engine suffixes, malformed thrust modes, boolean temperatures and unknown
bleed/anti-ice configuration. FLEX 300 C raised an exception. The candidate returns explicit
unavailable states instead of producing a target for those inputs.

Only exact existing engine identities are modeled. For example, PW1133GA-JM is no longer
silently reported as PW1133G-JM, and LEAP-1B28B1 is no longer reported as LEAP-1B28.
The public regulatory sheets list these separately; identical values in one static rating
column do not establish complete engine/model applicability. This correction restricts false
identity matching; it does not add engine profiles or establish simulator engine identity.
Recognized Boeing TO/TO-1/TO-2 and D- assumed-temperature forms remain distinct from
Airbus TOGA/FLEX/FLX. The existing labeled estimate formulas are unchanged.

The 100 C endpoint is the upper computational endpoint of the borrowed table, not a certified
aircraft envelope. Values below absolute zero, above that endpoint, or assumed temperatures
below OAT are refused. Numerical and configuration units remain explicit; no missing bleed/
anti-ice selection is silently treated as off. This does not establish the aircraft's actual
minimum/maximum operating temperatures.

Calibration now includes plan weight units as well as the existing aircraft/engine,
airframe/configuration, condition, runway and simulator-version scope. Adding the units field
invalidates earlier keys, so old readings require a fresh observation. Changed mass/weather/
configuration/build and the existing seven-day age limit prevent reuse. Invalid JSON,
timestamps, scope or readings leave the uncalibrated briefing available and request a new
reading. Supplying one observed N1 does not verify physical thrust or a full operating envelope.

Saved briefings now retain the method, assumptions and source anchors already returned in
structured estimator output. This implements the accepted D-09 disclosure requirement while
keeping spawn/thrust first and preserving the explicit estimate label and uncertainty range.

## Source and profile findings

| Profile | Existing method and source anchor | Current result and remaining verification |
| --- | --- | --- |
| A20N LEAP-1A26 | Pinned FlyByWire simulation table/corrections | Six independently executed source-port references agree; Infinite Flight engine/rating, native PERF and target behavior remain unobserved |
| A20N PW1124G1-JM / PW1127G-JM / PW1129G-JM | EASA flat-rating anchors plus explicitly borrowed simulation lapse | Software contracts pass; no independent PW N1 reference, error tolerance or simulator applicability is established |
| A21N PW1130G-JM / PW1133G-JM, including intended United case | EASA flat-rating anchor plus the accepted labeled estimate assumptions | No current simulator/livery engine identity or independent PW N1 schedule is established; real United tail evidence does not identify the simulator model |
| A21N LEAP-1A32 / -1A33 / -1A35A | Assumed corner point and borrowed LEAP-1A26 lapse, disclosed as assumptions | No rating-specific independent schedule or simulator observations; no family-wide accuracy claim |
| B38M LEAP-1B28 | Existing assumed corner, fixed-derate fractions and N1 exponent | TO/derate/ATM contract cases pass; no independent Boeing N1/derate schedule or simulator indication/calibration envelope is established |

Current public regulatory sources were retrieved directly without a paid provider or login:

- [EASA IM.E.093 Issue 14](https://www.easa.europa.eu/en/downloads/20016/en), October 16, 2026,
  lists exact PW variants and flat-rating anchors. PDF SHA-256:
  `f4a9a672f1288b7bf2a441c38f70b0f8d4cb44755af8d5c707b61b2aa5b8c24a`.
- [EASA E.115 Issue 09](https://www.easa.europa.eu/en/downloads/20810/en), March 23, 2026,
  distinguishes LEAP-1B models, configuration groups and identification plugs. PDF SHA-256:
  `c954619724652ce0025ca08afcb530e34766b610337931e45b11bc1853aa22f9`.
- The [frozen official v26 matrix](aircraft-catalog-v26.md) retains the published 26.5.2/build
  20344 baseline, app/OTA changes and native-system evidence gaps. That is not an observation
  of the owner's installed simulator. Documentation alone does not establish a usable native
  numerical PERF-to-N1 target.

No manufacturer N1 schedule or simulator accuracy reference is supplied by these sheets.
The [original source inventory](thrust-source-inventory.md) remains historical; its early
D-09 proposals were superseded by the accepted labeled-estimate decision in [goal.md](../goal.md).
No LEAP numerical reference is scored as a PW or Boeing accuracy reference.

## Independent source-port check

[Six reference cases](evidence/thrust-v045-reference.json) were generated by compiling and
executing the original FlyByWire `ThrustLimits_A32NX.hpp` and numeric helper functions at
commit `66021c24448c44399a8ff569eb14715b6b26558e`. The thrust header is unchanged;
SHA-256 `1d9871dd63e9b637eef18c6046dfe395b28a3e534a5e0ea3baa6ef8abe725bfd`.
Host-only SDK inheritance/types were replaced with a minimal declaration and `double` alias;
mathematical helper implementations were not rewritten. Original/helper/adapter hashes and
compiler receipts are retained privately. The reference does not import production Python
tables or the earlier Python test transcription.

Cases span -1,500 through 16,600 ft, cold/hot OAT, full/FLEX operation and bleed/anti-ice
combinations. The declared raw tolerance is 1e-9 N1 percentage points for a source-port
comparison; the displayed one-decimal rounding tolerance is 0.050000001 points. Neither is
an aircraft-accuracy tolerance. Per-profile accuracy tolerances remain unset until independent
reference and simulator observations exist.

Run the recorded software matrix, without providers or a model:

```sh
uv run --locked python scripts/evaluate_thrust.py --output artifacts/evals/v045-thrust.json
uv run --locked pytest tests/test_thrust_compatibility.py -q
```

The CLI separates 39 software contracts and six pinned-simulation source cases. Baseline
passes 26/45; candidate passes 45/45. The broader compatibility tests cover persistence,
calibration corruption/expiry/scope and retained briefings: baseline 28/57; candidate 57/57.
An initial storage-fixture setup error was corrected and both applications rerun with the
same corrected fixtures; the earlier diagnostic errors remain retained and are not used as
product evidence. Counts establish these contracts, not statistical quality or aircraft support.

The recorded numerical/software results are published as separate LangSmith experiments:
[baseline](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/83ec5f1c-43f7-4a4b-accc-bba4831cd367/compare?selectedSessions=22d33c85-57d9-4611-837c-c107782b6362) and
[candidate](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/83ec5f1c-43f7-4a4b-accc-bba4831cd367/compare?selectedSessions=3f078b21-c33b-4814-950f-f21c67b28d02). These experiments publish recorded deterministic outputs;
they do not call a model or a flight provider. The candidate source is
`170c4f1415613d8504c4f60d0937644847fcdd58`; later changes add assessment/runner reporting only.

The unchanged 28-case conversation suite passes on both controlled baseline and candidate,
using identical fixtures, clock and MCP transport. Initial actual-model attempts were blocked
by the ChatGPT Subscription Sharing limit. After Hudson increased the sharing cap from 10%
to 100%, the configured GPT-6-Luna/low connection succeeded at 23:31 UTC on November 11.
The [resumed evaluation report](../evidence/v045-evaluations.md) records the paired replay,
including failed WF-025 observations and a separately frozen explicit revision-sequence
supplement. It does not replace failed results with passing reruns. The existing model,
credential and billing route were reused; no credit purchase or provider change was needed.

## Open acceptance and operating limits

- Current-build simulator observations are not available in this assessment. Native PERF,
  engine/rating/livery identity, displayed target and usable manual setting must be observed.
  The operator was asked for the available device/build and authorized observation source.
  The [observation checklist](../verification/v045-simulator-observations.md) specifies the
  minimum identity/native-PERF and matched-case records. A follow-up Xcode/Windows check
  found no connected Apple device, Infinite Flight Windows package or running process.
- Each affected profile needs independent reference cases and an evidence-based numerical
  tolerance/envelope. A copied formula or a successful plan is insufficient.
- Model access is restored and targeted paired actual-model replay has run. The original
  WF-025 conversation/evaluation finding remains visible in the resumed report.
- Hudson approved a fresh allowance of four sequential Browserbase sessions, each capped
  at 180 seconds (720 seconds cumulative), and eight necessary FlightAware requests across
  PR/release acceptance. The existing one-workflow/two-waiter/30-second queue and cleanup/
  fencing controls remain unchanged. [PR live acceptance](../evidence/pr23-live-acceptance.md)
  passed using two sessions and two requests; two sessions and six requests remain reserved
  for exact release-image acceptance.
- Fresh PR live evidence covers the changed integration and passes all four BUILD-04
  outcomes. Exact-head product checks and the existing release/promotion gates remain
  separate requirements; no production promotion is claimed.

Verified aircraft support remains **0/51**. INT-412–414 remain open for profile/reference/
simulator acceptance, and INT-415 remains open for exact-candidate live validation and release.
v0.5 aircraft expansion, presets and trip-control features remain outside this patch.
