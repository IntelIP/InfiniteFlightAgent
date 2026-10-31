# Goal

Status: accepted product direction from Hudson's planning conversation, October 30, 2026. Implementation and verification have not begun.

## User and problem

Hudson uses Infinite Flight and currently asks ChatGPT to research flights, airport positions, schedules, and how to interpret SimBrief takeoff performance. The work is repeated across flights and aircraft. SimBrief already supplies the takeoff performance calculation; the missing step is translating its output into a manual thrust setting usable in Infinite Flight.

## Intended outcome

Enable Hudson to turn a conversational flight idea into a SimBrief flight plan and an actionable Infinite Flight briefing. The harness gathers missing information collaboratively and prominently supplies the manual spawn location and takeoff thrust target.

Example starting request: “I want to fly to Nice in Infinite Flight using an A320neo.” A complete request is not required. The harness helps resolve departure, date, aircraft, flight scenario, and dispatch details.

The control plane is ChatGPT, Claude, or Codex through MCP. ChatGPT is the primary intended conversational surface; an exclusive first-client delivery order has not been selected. Client compatibility must be established with live checks.

## Release scope

- Personal use first, built using Deep Agents SDK. Stable workflow portions may later be made explicit in LangGraph.
- Launch with the A320/A321neo family. Exact Infinite Flight variants and matching SimBrief airframe/engine profiles must be enumerated before implementation claims.
- Cover airline operations and private-flight scenarios, including multi-leg preparation.
- Gather flight identity, departure time, gate/terminal or FBO information using flight-data sources and internet research.
- Work with Hudson to establish sufficient SimBrief dispatch inputs; generate and retrieve the plan through the supported integration.
- Use SimBrief takeoff results to resolve the manual thrust target. Keep per-aircraft inputs and guidance explicit.
- Ground thrust resolution and protocols in current applicable professional performance/engine data or calculators, as requested October 30, 2026. Generic percentage rules and unsourced assumptions do not satisfy support criteria. Access and exact applicability remain research questions, not established capabilities.
- **Amended October 30, 2026 (Hudson):** labeled simulation-grade N1 estimates are acceptable where no professional source is available. An estimate must state its method, assumptions, source anchors (certified rating, flat-rating temperature, simulator-model shape), uncertainty range, and any calibration reading, and must be labeled as an estimate in the briefing. Unlabeled rules of thumb remain excluded.
- Provide import instructions for supported Infinite Flight fields and disclose any remaining setup. Import field coverage must be verified rather than assumed.
- Lead with bold spawn and thrust instructions. Supporting configuration, speeds, schedule, sources, assumptions, and limitations follow.

## What counts as aircraft support

**An aircraft counts once we can properly translate its takeoff performance calculation into an actionable manual thrust target in Infinite Flight.** Every aircraft has its own required inputs, supported method, conditions, and guidance. A common family method may be reused only with verified applicability to each aircraft.

Track this criterion in [aircraft coverage](aircraft-coverage.md), separately from overall dispatch workflow readiness. A listed airframe, successful SimBrief retrieval, or approximate community rule is not sufficient to mark an aircraft supported.

## Completion criteria for the usable release

1. Hudson can start from an incomplete flight idea in each intended client and receive focused clarification instead of having to prepare all dispatch inputs manually.
2. The harness resolves a dated airline flight or a private itinerary, gathers its schedule and airport-position information, and distinguishes reported real-world data from simulator recommendations.
3. The generated SimBrief plan matches agreed inputs. Each leg is preserved with its own identity, raw result, and briefing.
4. Launch aircraft meet the aircraft-specific support criterion, with documented translation methods and simulator verification.
5. The response prominently supplies spawn location and thrust target, preserving takeoff configuration, V-speeds, source identity, and important performance messages.
6. Changes to material inputs invalidate affected guidance. Missing information is explicit; partial results are not represented as complete.
7. Actual SimBrief generation, host access, and Infinite Flight import behavior are demonstrated at their respective evidence layers, with observed operating cost and latency.

## Expansion

After launch, add aircraft in batches toward coverage of the majority of Infinite Flight's ecosystem, prioritizing the most recently updated aircraft. Grouping by shared engines/methods can improve delivery efficiency while retaining aircraft-specific support checks. Define the current fleet denominator and what “majority” includes before declaring broad coverage.

## Boundaries

### Cost and operations preference — accepted October 30, 2026

Prioritize free/open-source technologies, openly licensed data, existing access, and low-maintenance integrations. Evaluate free public sources and applicable open-source methods before paid providers. Free access, open-source code, and open-data licensing are different properties; record each accurately. Consider setup, maintenance, reliability, and model/search cost as well as subscription price. Paid sources remain exceptions requiring a concrete coverage/access gap and separate approval. This preference does not lower the required standard for aircraft-specific thrust translation or silently remove historical/future flight and gate requirements. See [source strategy](research/free-first-strategy.md) for the proposed evaluation order.

The user operates Infinite Flight, selects spawn, imports the plan, and manually sets thrust. Automatic spawning, thrust control, climb management, LNAV/VNAV assistance, and telemetry-driven control are later possibilities, not launch requirements.

No public-product launch, paid provider, hosting platform, model provider, spending limit, or deployment is selected. Research can identify options; consequential choices remain with Hudson. See the [open decisions](backlog.md#open-decisions).
