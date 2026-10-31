# Roadmap

Status: proposed delivery sequence, October 30, 2026. No delivery dates or implementation completion are claimed. Product intent and support definitions are owned by [goal.md](goal.md).

| Milestone | User/engineering outcome | Exit condition | Backlog |
| --- | --- | --- | --- |
| M0 — Resolve integration feasibility | Know how the selected launch aircraft, SimBrief generation, flight data, and host connections can work together | Exact launch variants recorded; supported generation flow identified; thrust-resolution paths assessed; material access/decision blockers named | DISC-01 through DISC-05 |
| M1 — Establish the application foundation | A resumable personal dispatcher accepts a flight idea through MCP | Quality/validation bootstrap exists; shared contracts and storage work; one intended host completes a real low-risk request; other hosts have compatibility work recorded | SETUP-01, BUILD-01, BUILD-02 |
| M2 — Prepare a real flight collaboratively | Hudson can resolve missing details and obtain an identified SimBrief plan plus airport-position guidance | Research and generation work end to end; multi-leg identities survive; authentication handoffs and interruption recovery demonstrated | BUILD-03, BUILD-04 |
| M3 — Deliver launch-aircraft thrust guidance | SimBrief takeoff solutions become actionable manual targets for the selected A320/A321neo variants | Each selected variant passes its own thrust-support criteria and records limitations/evidence | BUILD-05, VERIFY-01 |
| M4 — Prove the usable release | The complete preparation experience works in Codex, ChatGPT, and Claude | Goal acceptance demonstrated; import field matrix verified; leading spawn/thrust response checked; failures, latency, and cost recorded | VERIFY-02, VERIFY-03 |
| M5 — Expand aircraft coverage in batches | More aircraft receive supported translations | Each batch uses an up-to-date fleet list, prioritizes recent aircraft updates, and meets per-aircraft acceptance | EXPAND-01 |

M0 investigations may reveal dependencies that change implementation order. M1–M3 can overlap where inputs are established; a development milestone is not release acceptance.

## Representative scenarios

- Launch-aircraft airline departure: dated flight identity, schedule, reported gate, matching simulator spawn, generated plan, and thrust instruction.
- Launch-aircraft private multi-leg itinerary: KIAD → EINN → LFMN, FBO/ramp guidance, separate plans and briefings, translation for each leg's conditions. This is a representative case, not an already validated route recommendation.
- Missing/changed data: unassigned gate, unavailable thrust reference, changed aircraft/runway/weather, interrupted generation, and recovery.
- The supplied B737 MAX 8 report is a preserved format example in the design, not an expansion of launch-aircraft scope.

## Stop and decision gates

- Do not promise a numerical thrust target where no applicable method/data exists. Record the limitation and pursue the specific research item.
- If a launch variant cannot be supported, bring the finding to Hudson; do not silently shrink launch scope.
- Select paid providers, model budgets, remote hosting, or access changes only with the applicable user decision.
- Complete required direct verification once; reopen only for a material change, failed/conflicting check, or unresolved acceptance issue.
- Do not commit, push, publish, deploy, or merge as part of planning or implementation authority alone.

## First integrated research case

Dulles–Newark with United A321neo is selected. DISC-09–11 in the [backlog](backlog.md) cover dated flight identity, gate/stand evidence, and PW thrust applicability. These can progress independently of SimBrief API generation access; no completed flight briefing is yet established.
