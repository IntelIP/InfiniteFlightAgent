# Infinite Flight Dispatcher

A personal flight-preparation agent accessible through MCP from ChatGPT, Claude, and Codex. Describe a flight idea, work with the harness to complete the necessary inputs, generate a SimBrief plan, and receive prominent manual spawn and takeoff-thrust instructions.

**Status: partial local implementation.** Python MCP preparation, explicit SimBrief retrieval, and immutable snapshots work. Generation, neo validation, client-app acceptance, and aircraft support remain incomplete. No remote repository or deployment exists.

See [local setup and usage](docs/implementation/simbrief-usage.md).

## Start here

| Document | Purpose |
| --- | --- |
| [Goal](docs/goal.md) | Accepted user outcome, launch scope, and completion criteria |
| [Roadmap](docs/roadmap.md) | Delivery sequence and milestone exit conditions |
| [Backlog](docs/backlog.md) | Focused work items, dependencies, acceptance, and open decisions |
| [Technical design](docs/technical-design.md) | Proposed architecture, workflow, contracts, and failure behavior |
| [Aircraft coverage](docs/aircraft-coverage.md) | Aircraft-specific translation support and evidence |

## Initial dependency research

Public-source investigation completed October 30, 2026; live access and aircraft support remain unverified:

- [SimBrief MCP extension](docs/research/simbrief-extension.md): pinned upstream source, reuse/extension requirements, legacy versus API v2 access questions.
- [Flight and gate data sources](docs/research/flight-data-sources.md): current, historical, and future data; provider costs, retention, and evaluation plan.
- [Professional thrust sources](docs/research/professional-thrust-sources.md): current OEM/professional options, evidence limits, and aircraft-specific translation plan.
- [Free-first strategy](docs/research/free-first-strategy.md): revised evaluation order prioritizing free/open sources and low operating overhead while retaining thrust-quality requirements.
- [Integration blueprint](docs/research/integration-blueprint.md): concrete SimBrief extensions, other MCP/data tool boundaries, a pinned open-source N1 calculation candidate, and remaining access/validation gaps.

- [Focused launch follow-up](docs/research/launch-dependencies-followup.md): current SimBrief retrieval rules, official neo engine families, observed free Avinor gates, and remaining reference/simulator gaps.

## Intended briefing

> **SPAWN: [Infinite Flight gate, FBO, or ramp position]**  
> **TAKEOFF THRUST: [supported target and engine indication]**
>
> Flight identity, departure time, SimBrief plan/import instructions, takeoff configuration, V-speeds, sources, and limitations follow.

Placeholders illustrate the response format; they are not calculated flight guidance.

## Local project

- Home: `/Users/hudson/Documents/GitHub/Products/InfiniteFlightDispatcher`
- Branch: `main`; no initial commit or remote is created by the planning setup.
- This is a new project. It does not restore the retired InfiniteFlight repository or its tracker commitments.
- Implementation, installations, external account changes, purchases, publication, and deployment are separate from this planning setup.
- Python was accepted by Hudson. Install with `uv sync --locked`; see the usage guide for MCP configuration.

See [AGENTS.md](AGENTS.md) before working here. Planning files are the current work-management source; no external tracker is selected.
