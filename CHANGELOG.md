# Changelog

All notable changes to Infinite Flight Agent are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is below 1.0,
a minor release may change behavior.

The version lives in `pyproject.toml`. Each release creates a `vX.Y.Z` Git tag and GitHub
Release from its section below, and labels the deployed Cloudflare Worker version the same way.
A running server reports its version at `/health`.

## [Unreleased]

### Added

- Bounded Browserbase management for the single-user dispatcher: one active workflow,
  two FIFO waiters, a 30-second queue wait, a three-minute session lifetime, and idle cleanup.
  Admission uses the existing transactional store, and unconfirmed releases remain fenced.
- Read-only `browser_status` MCP inspection and `ifd-simbrief sessions` / `cleanup` commands.
  Cleanup targets only dispatcher-owned sessions older than the session budget.
- Queue, deadline, release-confirmation, and minimum-adjusted browser-minute telemetry.

### Changed

- Browserbase requests use short timeouts without automatic retries. Browser commands and
  cleanup are bounded, disconnected sessions end automatically, and timed-out workflows do
  not open replacement browsers. The daily keepalive route skips browser work; login refresh
  happens on demand. Remote admission limits outstanding agent turns to six.

Local checks and isolated Cloudflare staging acceptance pass. Two retained A20N plans used
two non-overlapping browser sessions and increased reported usage by two minutes. These
controls have not been deployed to production; see [live acceptance](docs/evidence/pr20-live-acceptance.md).

## [0.4.1] - 2026-11-08

### Fixed

- SimBrief generation runs Route Finder when no route was supplied, after airport/date/runway
  updates finish, and waits for the routing result. Explicit routes are preserved. Empty or
  direct-only automatic results stop for review before Generate instead of silently producing DCT.
- Each active dispatcher execution lazily opens one Browserbase session and Playwright
  connection for its SimBrief operations. Parallel browser tools serialize on the owning
  thread. The session is released on completion, error or an approval pause; separate
  workflows remain isolated. Local chat and the live E2E runner use the same lifecycle.

Local regression tests cover session reuse, isolation, cleanup, approval pauses and routing.
Live Browserbase acceptance remains pending: its API rejects new sessions after the free
billable-minute allowance was exhausted. This release does not claim new live acceptance.

## [0.4.0] - 2026-11-07

### Fixed

- SimBrief-supplied routes no longer fail a blank-route readback. Explicit routes still
  must match. The approved runway is selected after the departure-time prompt resets it.
- Generation failures return `clicked` and `retryable`. Safe failures before Generate may
  be corrected and retried once; an atomic database claim prevents a second Generate click
  across threads or restarts. Repeating dispatch cannot erase generation history.
- Overlapping SimBrief dialogs are handled from the front. Unknown warnings stop for review.
- Connection durations are computed in a tool before recommendations. The prompt avoids
  redundant confirmation of settled flights and labels airport field elevation explicitly.
- Briefings expose SimBrief fuel/range/weight failures and preserve provider messages.
  Infeasible plans withhold thrust-setting guidance. A generated OFP is distinct from a
  feasible flight; the observed KLAX–NZAA plan had negative landing fuel and a range warning.

### Added

- Guided full-throttle N1 calibration and percentage targets. Saved readings require a
  simulator version, exact aircraft/engine/conditions/runway match, and an age of at most
  seven days. No engine model or supported-aircraft claim changes.
- Dated arrival-target calculations using sourced gate-to-gate block time, with explicit
  timezone/date-line handling and comparison to the generated plan's arrival.
- Explicit route, runway, load and SimBrief airframe selection. The retained OFP checks the
  selected airframe id. Simulator configuration/capacity and its source are kept separate
  from the provider profile; supplied capacity uses the dispatch's explicit KGS/LBS units.
- Saved-trip listing, per-leg status/briefings, revision comparisons, approved revisions,
  briefing refresh with changes, and persisted conversation/approval inspection after restart.
- Per-turn FlightAware list-price measurements and Browserbase elapsed time (no invented
  Browserbase/model invoice costs); versioned traces and objective workflow feedback.
- `scripts/review_traces.py` for bounded conversation review and optional LangSmith queueing;
  `evals/run_workflow_replay.py` for real-model generation/recovery/briefing regression with
  controlled providers and zero FlightAware/Browserbase calls.

Live acceptance is recorded separately after deployment; see [the implementation and
validation report](docs/evidence/trace-driven-release.md). No new aircraft-support claim is made.

## [0.3.1] - 2026-11-02

### Fixed

- **Thrust warnings are printed in the briefing.** The estimator's warnings only appeared in
  its structured notes, so whether a pilot saw them depended on the model relaying them. In the
  v0.3.0 live test it didn't, for a Denver estimate that was flagged as suspect. The TAKEOFF
  THRUST line now ends with them, most serious first, for example:
  `set N1 0.880 x full-thrust N1 (range 0.825-0.934) — SUSPECT: thrust reduction over the 25%
  FAA AC 25-13 limit; high altitude (5,511 ft): engine behavior extrapolated, wider range`.
  The thrust result also gains a `warnings` list. Informational notes stay out of the line,
  and N1 values are unchanged.

## [0.3.0] - 2026-11-02

### Added

- **Takeoff N1 estimates at high-altitude airports.** The estimator now uses all 21 of
  FlyByWire's A32NX takeoff rows, covering pressure altitudes from -2,000 to 16,600 ft instead
  of -2,000 to 2,000 ft. Airports such as Denver (about 5,400 ft) get an N1 target where they
  used to get "unavailable". The rows are copied verbatim from `ThrustLimits_A32NX.hpp` at the
  same pinned commit, and a test checks the port against a line-by-line transcription of
  FlyByWire's formula from -1,500 to 16,600 ft.

### Changed

- **Wider ranges above 2,000 ft.** There the engine's corner point (the temperature up to which
  it holds full rated thrust) follows FlyByWire's LEAP-1A26 altitude lapse. Engines with the
  same sea-level rating can differ at altitude (EASA E.110), so the corner tolerance grows by
  25% of the corner's drop from its 2,000 ft value, about +/-3 C more at Denver. The briefing
  says when this applies. Estimates at or below 2,000 ft are unchanged; 270 combinations were
  compared with v0.2.1.
- **Bleed corrections follow FlyByWire at 8,000 ft and above**, where its pack and anti-ice
  N1 corrections are larger. This affects the FlyByWire reference N1 shown for the A320neo.
- The approval prompt's thrust note uses the new range, so Denver now reads "estimate
  available".

Large FLEX reductions at high airports can trip the existing FAA AC 25-13 check (more than a
25% thrust reduction) and be flagged as suspect. On a real Denver A321neo plan (FLEX 47 C at
5,456 ft) the estimate is 0.862 x full-thrust N1 (0.810-0.920) and carries that flag,
suggesting the extrapolated corner point is conservative there.

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

[Unreleased]: https://github.com/IntelIP/InfiniteFlightAgent/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/IntelIP/InfiniteFlightAgent/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/IntelIP/InfiniteFlightAgent/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/IntelIP/InfiniteFlightAgent/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/IntelIP/InfiniteFlightAgent/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/IntelIP/InfiniteFlightAgent/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/IntelIP/InfiniteFlightAgent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/IntelIP/InfiniteFlightAgent/releases/tag/v0.1.0
