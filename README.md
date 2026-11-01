# Infinite Flight Agent

<p align="center">
  <strong>Tell it the flight you want to fly. Get a real-world flight, a SimBrief plan, and the gate and takeoff N1 to set in Infinite Flight.</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="docs/implementation/agent-usage.md">Agent guide</a> ·
  <a href="docs/implementation/deployment.md">Self-host on Cloudflare</a> ·
  <a href="docs/aircraft-coverage.md">Aircraft coverage</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>

<p align="center">
  <a href="https://github.com/IntelIP/InfiniteFlightAgent/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/IntelIP/InfiniteFlightAgent/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: GPL-3.0-only" src="https://img.shields.io/badge/license-GPL--3.0--only-blue"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="MCP server" src="https://img.shields.io/badge/MCP-server-black">
</p>

Infinite Flight Agent is an open-source AI dispatcher for [Infinite Flight](https://infiniteflight.com) pilots. It turns a plain-language idea like *"Dulles to Denver tomorrow evening in the A321neo"* into a briefing ready to fly. It runs on your own keys and your own ChatGPT plan, from the terminal or any MCP client.

```text
**SPAWN:** Gate C28 — used by the most recent completed UA599 (2026-10-30, FlightAware); today's gate is not assigned yet
**TAKEOFF THRUST (simulation-grade estimate):** FLEX, LEAP-1A32: set N1 0.911 x full-thrust N1 (range 0.865-0.948)

**Flight:** UA599 KIAD → KDEN · real aircraft A21N
**Departure:** sched out 2026-11-01 17:20 EST (2026-11-01T22:20:00Z)
**SimBrief plan confirmed:** KIAD 01R -> KDEN 16R · A21N LEAP-1A32 · FL360 · 1259 nm · ETE 03:27:38 · block fuel 11872 kgs
**Takeoff:** rwy 01R · flaps 1 · V1/VR/V2 155/159/161 · bleeds ON
```

<sub>A briefing from a live end-to-end run on October 31, 2026 (registration and codeshares removed).</sub>

## Why pilots use it

- **Fly real flights.** It searches live and recent schedules through [FlightAware AeroAPI](https://www.flightaware.com/commercial/aeroapi/), so it never invents a flight number. If today's gate isn't assigned yet, it gives the gate from the most recent operation and labels it historical.
- **Generate your SimBrief plan for you.** Once you approve, it fills SimBrief's dispatch form in a cloud browser, reads every field back, and generates exactly one plan per leg.
- **Lead with what you set first.** Every briefing opens with where to spawn and what N1 to set, before the details.
- **Know where the thrust number comes from.** Takeoff N1 is estimated from SimBrief's own takeoff solution (thrust mode, FLEX temperature, runway conditions), using the lapse shape of FlyByWire's open A32NX thrust model. It covers the A320neo, A321neo, and 737 MAX 8, each labeled as an estimate with a range. Other aircraft get a clear "unavailable" instead of a guess.
- **You approve before anything happens.** Nothing is generated until you approve the exact flight, airports, aircraft, and thrust status shown back to you.
- **Use it where you already chat.** Use the terminal chat, or connect ChatGPT, Claude, or Codex to the MCP server.

## How it works

```mermaid
flowchart LR
  you([You]) -->|"flight idea"| agent["Dispatcher agent<br/>(Deep Agents + your ChatGPT plan)"]
  agent -->|"real flights, gates"| fa[(FlightAware AeroAPI)]
  agent -->|"approval"| you
  agent -->|"fill and generate"| bb["Browserbase cloud browser"] --> sb[(SimBrief)]
  sb -->|"OFP + takeoff performance"| agent
  agent -->|"spawn + N1 briefing"| you
```

One agent handles the conversation and judgment calls. Fixed tools handle the parts that must be exact: flight lookup, approval, plan generation, matching the generated plan to the leg, and the thrust estimate. Details are in the [agent guide](docs/implementation/agent-usage.md) and the [technical design](docs/technical-design.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/), a ChatGPT plan, a [FlightAware AeroAPI](https://www.flightaware.com/commercial/aeroapi/) key (the Personal tier is enough), a [SimBrief](https://www.simbrief.com) account with a Navigraph email and password, and a [Browserbase](https://www.browserbase.com) API key.

```bash
git clone https://github.com/IntelIP/InfiniteFlightAgent.git
cd InfiniteFlightAgent
uv sync --locked
cp .env.example .env        # add AEROAPI_KEY, SIMBRIEF_USERID, BROWSERBASE_API_KEY,
                            # NAVIGRAPH_USERNAME and NAVIGRAPH_PASSWORD
uv run ifd-login            # Sign in with ChatGPT and approve plan usage
uv run ifd-chat             # describe your flight
```

The cloud browser signs in to SimBrief by itself with your Navigraph email and password, and keeps that login between runs. If you sign in to Navigraph with Google, Apple or Microsoft, set a Navigraph password first, or run `uv run ifd-simbrief` to sign in once by hand. Approval prompts appear in the terminal. See the [agent guide](docs/implementation/agent-usage.md) for all settings, resuming conversations, and MCP client setup.

## Choose how to run it

| Path | Best for | Start |
| --- | --- | --- |
| Terminal chat | Trying it out, single machine | `uv run ifd-chat` |
| Local MCP server | Claude Desktop, Codex, or other MCP clients on your machine | [MCP setup](docs/implementation/simbrief-usage.md) |
| Self-hosted remote MCP | Using it from ChatGPT or your phone, behind Cloudflare Access | [Cloudflare deployment](docs/implementation/deployment.md) |

The self-hosted path runs a Cloudflare Worker and container, with Neon Postgres for conversation state, R2 for screenshots, and Doppler for secrets. It is built for one owner and is not a shared or resold service.

## Quality

The agent is checked against [100 scripted first messages](evals/dispatch_prompts.jsonl) across 11 categories: vague requests, multi-leg trips, private flights, unsupported aircraft, and more. On October 31, 2026, two consecutive full runs on the same code passed every safety check 100% of the time, and fully passed 92 and 91 of the 100 cases. The safety checks are: no invented flight numbers, no assumed dates, correct airports, and unsupported thrust disclosed before approval. A separate live end-to-end set exercises approval, real SimBrief generation, and the final briefing. See [evaluation results](docs/implementation/agent-usage.md#full-100-case-runs--october-31-2026).

## Status and limits

- **Early, personal-use software.** It works end to end locally and on the self-hosted Cloudflare deployment, which planned its first live private flight on November 1, 2026.
- **Thrust targets are simulation-grade estimates**, shown with a range. No aircraft is yet marked as verified against reference data; see [aircraft coverage](docs/aircraft-coverage.md).
- **FlightAware only sees about two days ahead.** Flights further out have no live schedule or gate.
- **It does not control the simulator.** It never claims your plan was imported, your aircraft spawned, or your thrust was set.

> For flight simulation only. Never use any output of this project for real-world flight planning or aircraft operation.

## Contributing

Issues and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and the evaluation rules, and the [code of conduct](CODE_OF_CONDUCT.md). Checks that need no provider keys:

```bash
uv run ruff check src tests
uv run pytest -q
```

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md). The [roadmap](docs/roadmap.md) and [backlog](docs/backlog.md) show what's next.

## License

[GPL-3.0-only](LICENSE). The takeoff N1 estimator ports the thrust-limit lapse shape of FlyByWire A32NX `ThrustLimits_A32NX.hpp` (GPL-3.0, commit `66021c2`), so the whole project is distributed under the GPL. Bring your own keys and compute: no credentials, hosted service, or ChatGPT plan access are included.

Infinite Flight Agent is an independent project. It is not affiliated with or endorsed by Infinite Flight LLC, FlightAware, SimBrief or Navigraph, Browserbase, OpenAI, or FlyByWire Simulations. All trademarks belong to their owners.
