# Jumpseat working guidance (repository: InfiniteFlightAgent)

Read the workspace guidance and [goal](docs/goal.md), then the relevant [backlog item](docs/backlog.md) before starting work. The [roadmap](docs/roadmap.md) is an index of outcomes; the [technical design](docs/technical-design.md) contains engineering proposals. Keep decisions in their owning document and link rather than copying them across plans.

## Authority and current state

- This repository now includes a partial local Python MCP implementation. See docs/implementation/simbrief-usage.md for implemented behavior and blockers. No aircraft support is established.
- User-selected product requirements live in `docs/goal.md`. Engineering proposals and unresolved questions must remain distinguishable from accepted decisions and observed results.
- Work planning lives in `docs/backlog.md`. Do not create AgentShift, Plane, or other tracker items without direction.
- Ask before Git commits or pushes. Local Git initialization does not authorize publication, remote creation, or deployment.
- Provider/model choices, paid calls, subscriptions, infrastructure, and external account changes require the applicable user authorization. Do not treat this document as that authorization.

## Product invariants

- SimBrief supplies the takeoff performance solution; our component resolves an aircraft-specific manual thrust target from it.
- An aircraft counts as supported when its thrust translation meets its documented acceptance and verification requirements. Overall workflow readiness is tracked separately.
- Retain raw performance inputs, units, assumptions, messages, and source identity. Never invent N1 or derive it from a generic throttle/derate percentage.
- Keep engine target, thrust mode, assumed/FLEX temperature, and throttle position distinct.
- Distinguish an assigned real-world gate from a recommended simulator spawn position.
- Lead the briefing with spawn and thrust instructions, including explicit unavailable states.
- Never claim the plan was imported, aircraft spawned, or thrust set unless observed at that layer.

## Implementation prerequisites

Before application implementation or first code review, complete `SETUP-01` in the backlog: select language, run the workspace quality bootstrap, install pinned language-matched dead-code checks, add `tabellio.validation.json`, add actual-PR-head product-validation CI, and define durable validator evidence. These checks are not installed by this planning setup. Do not classify the eventual application as non-product to bypass them.

Use the relevant Deep Agents/LangGraph skills and current official references. Use `validate-product` for changes to behavior, AI/structured output, external resources, cost, or safety; use `pr-workflow` when publication is requested. Required validation is `passed`, `failed`, or `blocked`, with exact-candidate evidence. Mocked tests do not establish live integration or simulator behavior.

For material agent architecture questions, retrieve relevant sections from the curated knowledge root `/Users/hudson/Library/Application Support/AgenticEngineering` using OpenWiki search/read, as directed by workspace guidance. Do not initialize a generated code wiki over that collection. This task does not authorize knowledge-base or memory writes.

## Code cleanup

- Run `bash scripts/check-dead-code.sh` after removing code and before review.
- For cross-file changes, run `graphify update .`, inspect callers and dependencies, and verify findings in current source and framework registrations.
