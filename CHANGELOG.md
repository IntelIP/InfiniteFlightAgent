# Changelog

All notable changes to Infinite Flight Agent are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is below 1.0,
a minor release may change behavior.

The version lives in `pyproject.toml`. Each release creates a `vX.Y.Z` Git tag and GitHub
Release from its section below, and labels the deployed Cloudflare Worker version the same way.
A running server reports its version at `/health`.

## [Unreleased]

## [0.2.1] - 2026-11-02

### Fixed

- **Tool calls keep their arguments when the model makes several at once.** For a multi-call
  response the ChatGPT-plan route sends each call's arguments only on its final stream event,
  and langchain-openai builds arguments from incremental deltas alone, so every call arrived
  empty. In the v0.2.0 live test the dispatcher's first four flight searches failed this way
  before a single search succeeded. The model adapter now passes those final arguments
  through.
- **A finished leg's briefing is no longer held back.** When the dispatcher finished a leg and
  went straight to the next leg's approval, the first briefing only appeared at the very end.
  An approval prompt now carries the briefings finished earlier in the same turn (a
  `briefings` field in the MCP response; the terminal chat prints them first).
- **The approval prompt's takeoff thrust note checks the departure airport.** It said
  "estimate available" for any supported aircraft, even at Denver, where the thrust model has
  no data. It now uses the airport's elevation: available, "may be unavailable" near the edge
  of the modeled band, or unavailable, for example `A21N at KDEN (5,434 ft)`.
- **Tests cannot reach the internet.** A local test run had made one real FlightAware airport
  lookup through a missed stub; tests now fail on any request that leaves the machine.

## [0.2.0] - 2026-11-01

### Fixed

- **Multi-leg connections are checked in code.** A leg must depart at least 45 minutes after
  the trip's previous leg is scheduled to arrive. The approval gate refuses a leg that does not
  connect before you are asked to approve it, and `dispatch_flight` enforces the same rule. In
  a live test the dispatcher had proposed a second leg that left before the first one landed.
- **The approval prompt shows the departure time.** Every dispatch now carries its departure
  time. The prompt shows it in the origin's local time and in UTC and, for a later leg, the
  connection after the previous leg arrives (for example "Connection: 5 h 08 min after leg 1
  arrives"). Before, an airline leg's approval had no time on it.

### Added

- Version tracking: this changelog, `version` in the `/health` response, and Release workflow
  checks that refuse to re-release an existing version or ship one without a changelog entry.
  Each release creates its Git tag and GitHub Release and names the Worker version after it.

### Changed

- `dispatch_flight` requires `departure_utc` for airline flights as well as private ones
  (the occurrence's scheduled departure from the flight search).
- The README is reorganized for new users and contributors.

## [0.1.0] - 2026-11-01

First public release, and the first version live on the self-hosted Cloudflare deployment.

### Added

- Dispatcher agent (Deep Agents on your ChatGPT plan): turns a flight idea into a briefing
  that opens with where to spawn and the takeoff N1 to set.
- Real flights, gates and equipment from FlightAware AeroAPI, never invented.
- SimBrief plan generation in a Browserbase cloud browser after your approval, with every
  field read back and at most one generation per approved leg.
- Simulation-grade takeoff N1 estimates for the A320neo, A321neo and 737 MAX 8, derived from
  SimBrief's takeoff solution and FlyByWire's open A32NX thrust model.
- Terminal chat, a local MCP server, and a self-hosted remote MCP server on a Cloudflare
  Worker and container behind Cloudflare Access, with Neon Postgres, R2 and Doppler.
- Automatic SimBrief sign-in with your Navigraph email and password, a saved login that is
  recreated if Browserbase loses it, and a daily keep-alive
  ([#3](https://github.com/IntelIP/InfiniteFlightAgent/pull/3)).
- Evaluations replay synthetic or recorded FlightAware data by default ($0 in FlightAware
  fees); live checks are opt-in and capped at $1 per batch
  ([#4](https://github.com/IntelIP/InfiniteFlightAgent/pull/4)).
- Product validation passes only on recorded live acceptance for the deployed code
  ([#6](https://github.com/IntelIP/InfiniteFlightAgent/pull/6)).
- Paid-operations kill switch and an Emergency stop workflow.
- GPL-3.0 license, contributing guide, security policy and code of conduct.

### Fixed

- The deployed server reconnects to Neon after idle connections drop, instead of failing
  every request until a restart ([#2](https://github.com/IntelIP/InfiniteFlightAgent/pull/2)).
- A SimBrief generation that fails before the Generate click leaves the leg retryable instead
  of blocking it permanently ([#3](https://github.com/IntelIP/InfiniteFlightAgent/pull/3)).

[Unreleased]: https://github.com/IntelIP/InfiniteFlightAgent/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/IntelIP/InfiniteFlightAgent/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/IntelIP/InfiniteFlightAgent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/IntelIP/InfiniteFlightAgent/releases/tag/v0.1.0
