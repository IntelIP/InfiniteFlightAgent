# Flight research tools plan: FlightAware AeroAPI for Managed Deep Agents

October 30, 2026. Status: **plan; nothing in this document is implemented.** Scope: BUILD-03 flight identity, schedule, and reported-gate research for DISC-09/DISC-10. Simulator stand mapping and thrust are out of scope.

Authority: Hudson approved FlightAware AeroAPI Personal on October 30, 2026 (backlog D-04) and directed that these tools run inside a Managed Deep Agents (MDA) agent. Building the tools locally is in scope. Deploying to LangSmith, choosing the model provider (D-03), and uploading the AeroAPI key to a hosted secret store each need separate approval.

## Evidence this plan is built on

Live AeroAPI v4 calls on October 30, 2026 (about 6 result sets, ~$0.03). Raw responses are kept outside the repository, because the terms for storing FlightAware data are not yet confirmed.

| Question | Endpoint | Observed result |
| --- | --- | --- |
| Departures from KIAD leaving the gate 22:00–22:15 local | `GET /airports/KIAD/flights/scheduled_departures?type=Airline` | 14 flights in the window. Across all 45 flights returned: flight number, scheduled and estimated gate departure, and aircraft type 45/45; gate 43/45 (the 2 without one included a UPS cargo flight); registration 44/45; terminal 0/45 (Dulles encodes the concourse in the gate). |
| United KIAD→KEWR, Oct 28–31 | `GET /airports/KIAD/flights/to/KEWR?connection=nonstop` | 5 daily United flights (UA1359, UA2396, UA2823, UA1831, UA1997). Departure and arrival gates, aircraft, registration, and scheduled/actual times present. Also returned cargo flights with null times and gates (MTN, FX). |
| The flight number in the latest SimBrief plan (UA2408) | `GET /flights/UAL2408?ident_type=designator` | The real UA2408 is DEN→IAD on an A321neo. The plan's KIAD→KEWR UA2408 does not exist. Flight numbers in user-made plans must be checked against the real route. |

Endpoint constraints from the published OpenAPI spec (4.17.1):

- `start`/`end` can be at most 10 days in the past and 2 days in the future.
- `scheduled_departures` filters on `scheduled_off` (takeoff time), not `scheduled_out` (gate departure).
- One result set is up to 15 records.
- Personal tier: $0.005 per result set for airport board queries, 10 result sets per minute, personal/academic use, no historical endpoints and no alerts. Per-result-set prices for `/flights/{ident}` and `/flights/to` were not checked individually.

## Tools

These are five read-only LangChain tools. Each is a thin wrapper over plain functions in the `ifdispatcher` package, so the existing local MCP server can expose the same operations without duplicating logic.

| Tool | Inputs | AeroAPI call | Use case |
| --- | --- | --- | --- |
| `find_airport_departures` | `airport` (ICAO), `local_date`, `start_local`, `end_local` (≤ 3 h), optional `airline`, `destination`, `include_cargo=false` | `scheduled_departures` for future windows, `departures` for past ones. Widen the query by the expected taxi time, then keep only flights whose `scheduled_out` falls in the window | "Which flights leave Dulles between 10:00 and 10:15 PM?" |
| `find_route_flights` | `origin`, `destination`, `local_date` (or a span ≤ 3 days), optional `airline`, `include_cargo=false` | `/airports/{origin}/flights/to/{destination}?connection=nonstop` | "What real United flights go IAD→EWR on Saturday?" |
| `get_flight_by_number` | `flight_number` (IATA or ICAO), optional `local_date`, `origin` | `/flights/{ident}?ident_type=designator` with a bounded date range | "Is UA2408 real, and where does it fly?" |
| `refresh_flight_observation` | `fa_flight_id` from a prior result | `/flights/{fa_flight_id}` | Re-check gate, aircraft, and estimated times close to departure |
| `match_simbrief_plan_to_schedule` | `trip`, `leg`, `revision` of a saved SimBrief snapshot | Reads the local snapshot, then calls `find_route_flights` and `get_flight_by_number` | Reports `matched`, `flight_number_mismatch`, `equipment_differs`, or `no_real_flight`, with the nearest real candidates by departure time and aircraft |

Excluded on purpose: flight search, positions, tracks, maps, Foresight, alerts, and any write operation. None is needed for this use case, and some are outside the Personal tier.

### Result envelope

Every tool returns the shared envelope from the [integration blueprint](../research/integration-blueprint.md#other-data-and-mcp-integration-boundary): `status`, `data`, `source_refs`, `observed_at`, `validity`, `missing_inputs`, `errors`.

Each flight record includes:

- **Identity:** operating flight number (IATA and ICAO), codeshares, operator, `fa_flight_id`, origin and destination (ICAO and IATA).
- **Times:** scheduled, estimated, and actual gate-out and takeoff, each in UTC and airport-local time.
- **Positions:** departure gate and terminal, arrival gate and terminal.
- **Equipment:** `aircraft_type` and `registration`.
- **Status:** FlightAware status text.
- **Temporal class:** `historical`, `current`, or `future_schedule`.
- **Per-field state:** `reported` or `unavailable`. A missing value is never inferred.

`source_refs` names "FlightAware AeroAPI v4", the endpoint, the query window, and the observation time.

### Rules the tools enforce in code

- **Read-only.** Every tool is a GET.
- **Simulator data stays separate.** No tool states a simulator spawn or the simulator aircraft.
- **Gates.** A gate is reported only for its own dated flight. Gates and aircraft for upcoming flights are labeled as current assignments that may change.
- **Codeshares.** Regional flights are kept under their operating carrier (YX, YV, G7, C5, …) with the marketing numbers listed. When filtering by airline, operating and marketing numbers both count, so United Express flights aren't missed.
- **Validation.** Airport codes, dates, and windows are checked before any call. Requests outside AeroAPI's date range return `missing_inputs` or `unsupported_window` without making a call.
- **Cost limits.**
  - `max_pages` is capped at 3 per call (at most ~$0.015 for an airport board).
  - A 60-second in-memory cache, keyed by request path, absorbs repeated agent reads.
  - Identical concurrent requests share one call.
  - No polling loops.
  - A per-run limit on tool calls through `ToolCallLimitMiddleware`; the starting value is set from measured runs.
- **Errors.**
  - 401 says "invalid key or endpoint above Personal tier".
  - 429 returns `rate_limited` without retrying.
  - Network and malformed responses are classified. A failure never returns partial data as complete.
- **The key.** Read from the `AEROAPI_KEY` environment variable and sent only as the `x-apikey` header. Never logged, returned, or written to agent memory.
- **Storage.** Raw responses are not placed in the agent's shared memory or durable store until FlightAware's data-storage terms are confirmed. Tool results carry the normalized fields plus source references. Snapshots for briefings may keep normalized values with `observed_at` and `source_refs`.

## Managed Deep Agents integration

| MDA element | Plan |
| --- | --- |
| Language and package | Python, matching the existing `ifdispatcher` package and the `managed-deepagents` PyPI CLI |
| Tools | `tools/flights.py` holds `@tool(parse_docstring=True)` wrappers that import from `ifdispatcher.flights` and are passed to `define_deep_agent(tools=[...])`. Docstrings state the inputs, window limits, and that results are real-world observations, not simulator positions. |
| Secrets | Local `mda dev`: `AEROAPI_KEY` from the Git-ignored project `.env` (already present). Hosted: `mda deploy` forwards non-reserved `.env` entries as deployment secrets, or use an agent-owned connection (`mda connections create aeroapi --secret-from-env AEROAPI_KEY`). Either way the key leaves this Mac, so hosted use needs Hudson's approval. |
| Middleware | `ToolCallLimitMiddleware` for the per-run budget. No PII middleware is needed for flight data. |
| Human-in-the-loop | None for these read-only tools. SimBrief generation and other mutating tools keep their own approval gates. |
| Memory | Off (no `memory.py`). MDA memory is shared by all callers and must not hold provider payloads or credentials. |
| Sandbox | None (`mda init --no-sandbox`). The tools need no shell or filesystem. |
| Instructions | `instructions.md` sets the order for an airline flight: resolve the real flight, compare it with the SimBrief plan, report the gate as a dated observation, and keep simulator recommendations separate. |
| Evals | Harbor tasks come later, after the tools pass live checks: departure window, route lookup, flight-number mismatch, missing gate. |

Open integration questions, to resolve when implementing (check against the installed `managed-deepagents` version and current official docs):

1. **Project layout.** MDA builds only from the directory passed to `mda`, so `ifdispatcher` must sit inside that directory (repository root as the MDA project, or the package vendored inside it). Confirm with `mda build` before writing code.
2. **Persistence when hosted.** The existing SimBrief snapshots live in local SQLite (`IFD_DATA_DIR`). MDA manages the store and checkpointer, and sandboxes are per thread, so `match_simbrief_plan_to_schedule` needs a hosted-compatible snapshot location before deployment. Locally it reads the existing store.
3. **Flight-number conversion.** Confirm whether AeroAPI accepts IATA designators directly. If not, resolve them through the operators endpoint (cached for a long time) rather than an unpinned third-party airline list.
4. **Past departure windows.** The `departures` board (past windows) hasn't had a live test.

## Implementation steps

1. Add `ifdispatcher/flights/` with an AeroAPI client (key from the environment, timeout, error classes, page cap, cache), normalization into the flight record, and the five operations. Use only the standard library and existing dependencies; no new client SDK.
2. Write unit tests on small synthetic payloads labeled as synthetic, covering:
   - null gate, null times, cargo flights, codeshare filtering;
   - the takeoff-time filter widening;
   - the out-of-range date window;
   - 401/429/network errors;
   - the UA2408 mismatch logic.

   Committing trimmed real responses as fixtures waits until FlightAware's terms allow it.
3. Expose the same operations on the existing local MCP server, so they can be used before MDA is set up.
4. Scaffold the MDA wrappers (`tools/flights.py`, `agent.py`, `instructions.md`) and run `mda dev` locally with Hudson's approval of the model provider (D-03).
5. Live checks, recorded as `validate-product` evidence with observation times and result-set counts:
   - KIAD departures, 22:00–22:15 local;
   - KIAD→KEWR nonstops for a chosen date;
   - UA2408 reported as a flight-number mismatch;
   - one flight with no gate shown as `unavailable`;
   - refreshing one flight's gate near departure.
6. Then run `bash scripts/check-dead-code.sh` and the validator. Deployment stays separately gated.

## Acceptance

- **Tool results.** Each tool returns the envelope above for the live cases in step 5. Flight number, departure time, gate, and aircraft are present when FlightAware reports them, and explicitly `unavailable` when it doesn't.
- **SimBrief comparison.** `match_simbrief_plan_to_schedule` reports the UA2408 mismatch and the nearest real KIAD→KEWR United candidates.
- **Cost.** No tool call exceeds 3 result sets, and the measured cost per completed lookup is recorded.
- **Live check.** The tools work inside an MDA agent under `mda dev`, observed in LangSmith Studio. Unit tests alone don't establish this.
