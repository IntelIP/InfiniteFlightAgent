# Roadmap

Status updated November 12, 2026 UTC. Production is **v0.4.6**; its
[deployment and exact-image acceptance record](implementation/deployment.md#current-release-v046)
own the observed release facts. New release work is tracked in the
[Infinite Flight Agent Linear project](https://linear.app/intelip/project/infinite-flight-agent-a2f7101e32e9).
The [backlog](backlog.md) indexes current capability and historical research;
[goal.md](goal.md) owns accepted intent and the unchanged aircraft-support definition.

## Release outcomes

| Version | User outcome | Owning acceptance |
| --- | --- | --- |
| v0.4.2 — shipped | Automatic routing, retained plans and bounded single-user browser workflows | [Deployment and acceptance](implementation/deployment.md#current-release-v042) |
| v0.4.3 — shipped | Invalid revisions return useful validation; provider failures explain the cause; workflow evaluation has a versioned baseline | [Release evidence](evidence/v043-release.md); [INT-402–406](https://linear.app/intelip/issue/INT-406) |
| v0.4.4 — shipped | Existing conversations and routing are predictable across broader scenarios; the v26 catalog/native-capability matrix is recorded | [Release evidence](evidence/v044-release.md); [INT-407–411](https://linear.app/intelip/issue/INT-411) |
| v0.4.5 — shipped | Existing neo/MAX estimate paths enforce exact engine/condition identity, safe calibration reuse and retained disclosures; profile accuracy remains unverified | [Release evidence](evidence/v045-release.md); INT-415 release, INT-412–414 verification open |
| v0.4.6 — shipped | Numbered revisions finish generation and finalization in order while retaining previous OFPs/briefings and exact approvals | [Release evidence](evidence/v046-release.md); [PR #24](https://github.com/IntelIP/InfiniteFlightAgent/pull/24) |
| v0.5.0 — planned | Trips expose durable progress and safe cancellation/recovery, support more dispatch inputs and private configurations, and report measured aircraft expansion | [INT-416–428](https://linear.app/intelip/issue/INT-428) |

For this sequence, v0.4.x repairs and verifies existing behavior; v0.5 adds trip-control and
dispatch capabilities. v0.4.5 ships evidenced software corrections; its remaining profile
verification stays on INT-412–414. Linear owns the detailed task acceptance and actual
blocking relationships, rather than this map duplicating those specifications.

The first parallel wave shipped revision validation (INT-404), provider failures (INT-405)
and workflow evaluations (INT-403), with one integrator handling documentation (INT-402)
and release assembly (INT-406). Isolated worker branches were integrated in PR #21; CI,
exact-image acceptance and production promotion are recorded as distinct observed steps.

## Original product milestones and current gaps

| Milestone | Current capability | Remaining acceptance | Backlog |
| --- | --- | --- | --- |
| M0 — Resolve integration feasibility | The selected generation, flight-data and hosted MCP paths run | Exact launch engine/profile applicability and simulator findings remain incomplete | DISC-01 through DISC-08 |
| M1 — Establish the application foundation | Deployed Deep Agent, MCP, storage/checkpoints and runnable quality gates exist | Durable execution progress/cancellation and client-specific journeys are tracked separately | SETUP-01, BUILD-01/02; INT-416/417/426 |
| M2 — Prepare a real flight collaboratively | Approval, browser generation, route-correlated OFPs, retained multi-leg briefings and 28-case MCP evaluation are observed | Broader live-provider scenarios, configuration evidence and simulator parking correspondence | BUILD-03/04; INT-419/426 |
| M3 — Deliver launch-aircraft thrust guidance | Labeled estimates and observed-reading calibration are implemented | Zero aircraft currently meet verified support criteria; per-profile references and simulator cases remain required | BUILD-05, VERIFY-01; INT-412–414/420–425 |
| M4 — Prove the usable release | Remote MCP and deployment acceptance are observed | Full intended-client journeys, simulator import-field matrix and usable aircraft-specific instructions | VERIFY-02/03; INT-426 |
| M5 — Expand aircraft coverage in batches | Official v26 catalog/capability matrix is frozen; family-batch work is defined | Source-backed methods, resolved applicability and simulator verification for individual aircraft | EXPAND-01; INT-420–427 |

These milestones are distinct from release numbering. Shipping v0.5 does not automatically
complete all original launch or aircraft-support criteria.

## Aircraft expansion

[INT-409](https://linear.app/intelip/issue/INT-409) froze the [official fleet and v26 matrix](research/aircraft-catalog-v26.md):
51 current aircraft and 11 legacy records retained separately. Strict majority is 26 fully
verified current entries; verified support is zero. Engine/configuration, exact profile,
displayed-target and native PERF/FMS unknowns remain explicit. Partial profile support is
reported separately and does not reduce the raw denominator.

Priorities include the current Challenger 350, confirmed ACJ configurations and aircraft
with relevant v26 changes. An ACJ livery does not establish extra fuel capacity. Cockpit,
visual and fuel-system changes do not by themselves prove a thrust-model change. Native
indications are inspected before duplicating a capability in the dispatcher.

Numerical scenarios distinguish N1, EPR, torque and other applicable target types; no N1
formula is assumed universal. Scenario breadth, implemented estimates and simulator-verified
support have separate counts. Reference or simulator-access blockers stay visible. An
intermediate release reports its actual coverage and leaves unfinished expansion tasks open;
it cannot claim majority coverage or silently reduce the denominator.

## Evaluation and release evidence

- Use software-defined whole-scenario and persistent-state checks, not only unit tests or a preferred sequence of tool calls.
- Compare matched, versioned cases in LangSmith with code/fixture/verifier identity, useful workflow metrics and explicit invalid/missing-evidence outcomes.
- Keep scripted models/controlled services, real-model replay, live-provider acceptance, numerical references and simulator observations distinct.
- Preserve exact-input approval, immutable retained plans, Generate claims, bounded browser ownership and explicit unavailable thrust.
- Meet repository CI/product acceptance for the actual candidate. Live provider batches require an allowance; promotion retains the existing production approval gate and rollback identity.

## Representative scenarios

- Dated airline preparation with reported gate, simulator-mapping status, matched plan and appropriately qualified thrust instruction.
- Private multi-leg preparation with sourced aircraft configuration, FBO/ramp limitations, independently retained plans and per-leg guidance.
- Changed inputs, unsupported revision fields, rejected approvals, infeasible fuel/weight, unavailable targets, provider failures, uncertain generation and restart recovery.
- The original Dulles–Newark United A321neo case remains profile-specific verification work in DISC-09–11; successful generic neo dispatch does not complete that aircraft's simulator acceptance.
