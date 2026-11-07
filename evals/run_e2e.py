"""Live end-to-end checks: conversation -> approval -> SimBrief generation -> briefing.

WRITES to the user's SimBrief account (one plan per approved case) and uses Browserbase time,
FlightAware result sets, and ChatGPT plan usage. Run sequentially: finalize reads the latest
SimBrief plan. Results go to Git-ignored artifacts/evals/e2e-<stamp>/.

    uv run python evals/run_e2e.py [--ids E2E-01,E2E-04]
"""

import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from flight_data import FlightData

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ifdispatcher import core, flights, operations, simbrief_browser, workflow
from ifdispatcher.agent import build_agent
from ifdispatcher.config import data_dir, export_tracing_settings
from ifdispatcher.core import Store

ROOT = Path(__file__).resolve().parents[1]

# expect: generated (a plan must be generated and briefed), declined (no generation),
# existing (analyze the latest plan, no generation). thrust: estimated | unavailable | any.
CASES = [
    {
        "id": "E2E-01",
        "turns": ["A real United flight from Dulles to Denver tomorrow evening in the A21N."],
        "expect": "generated",
        "thrust": "estimated",
    },
    {
        "id": "E2E-02",
        "turns": ["Dulles to Boston tomorrow morning in the A20N, any real United flight is fine."],
        "expect": "generated",
        "thrust": "estimated",
    },
    {
        "id": "E2E-03",
        "turns": ["DCA to Chicago O'Hare tomorrow afternoon in the 737 MAX 8, any real airline."],
        "expect": "generated",
        "thrust": "estimated",
    },
    {
        "id": "E2E-04",
        "turns": [
            "Private flight KIAD to KTEB tomorrow at noon in the A320neo, callsign N320HD, 6 pax."
        ],
        "expect": "generated",
        "thrust": "estimated",
    },
    {
        "id": "E2E-05",
        "turns": ["Dulles to San Francisco tomorrow on a real United flight, I'll fly the 787-9."],
        "expect": "generated",
        "thrust": "unavailable",
    },
    {
        "id": "E2E-06",
        "turns": ["Dulles to London Heathrow tomorrow evening, real United flight, in the A21N."],
        "expect": "any",
        "thrust": "any",
    },
    {
        "id": "E2E-07",
        "turns": ["Dulles to Newark tomorrow morning in the A20N on a real United flight."],
        "expect": "declined",
        "thrust": "any",
        "decline": "Actually, not now.",
    },
    {
        "id": "E2E-08",
        "turns": ["I already generated my SimBrief plan. Just give me the gate and the N1."],
        "expect": "existing",
        "thrust": "any",
    },
    {
        "id": "E2E-09",
        "turns": [
            "Dulles to Denver tomorrow evening, real United flight, A21N. My full-throttle N1 in "
            "Infinite Flight reads 92%."
        ],
        "expect": "generated",
        "thrust": "estimated",
        "calibrated": True,
    },
]
CASES.append(
    {
        "id": "E2E-10",
        "turns": [
            "Private two-leg trip, A20N, callsign N320HD, 4 passengers, KGS, standard A20N airframe and default SimBrief route. Leg 1 KIAD to KEWR on November 8, 2026 at 17:00 UTC. Leg 2 KEWR to KIAD on November 8, 2026 at 21:00 UTC. Set up and generate both, one approval per leg, and deliver each briefing."
        ],
        "expect": "generated",
        "thrust": "estimated",
        "legs": 2,
    }
)

FOLLOW_UP = "Go with your best suggestion and set it up."


def tool_results(messages, name):
    return [json.loads(m.content) for m in messages if m.type == "tool" and m.name == name]


def run_case(case: dict, experiment: str) -> dict:
    # Credentials may come from the deployed database; flight requests and browser-context
    # bookkeeping stay in a temporary local store. Never write eval trips to production.
    context = Store(data_dir()).read_setting(simbrief_browser.STORED_CONTEXT)
    with (
        tempfile.TemporaryDirectory(prefix="ifd-e2e-") as directory,
        patch.dict(os.environ, {"IFD_DATA_DIR": directory}),
        patch.object(core, "open_store", lambda: Store(Path(directory))),
        patch.object(workflow, "_store", lambda: Store(Path(directory))),
        patch.object(operations, "open_store", lambda: Store(Path(directory))),
    ):
        if context:
            Store(Path(directory)).save_setting(simbrief_browser.STORED_CONTEXT, context)
        return _run_case(case, experiment)


def _run_case(case: dict, experiment: str) -> dict:
    agent = build_agent(checkpointer=InMemorySaver())
    config = {
        "configurable": {"thread_id": f"{experiment}-{case['id']}"},
        "run_name": case["id"],
        "tags": ["e2e", experiment],
        "metadata": {"case_id": case["id"], "experiment": experiment},
    }
    before, started = dict(flights.usage), time.time()
    approvals, error, payload = (
        0,
        None,
        {"messages": [{"role": "user", "content": case["turns"][0]}]},
    )
    replies = 0
    try:
        for _ in range(8):
            result = agent.invoke(payload, config=config, version="v2")
            if result.interrupts:
                approvals += 1
                if case.get("decline"):
                    decision = {"type": "reject", "message": case["decline"]}
                else:
                    decision = {"type": "approve"}
                payload = Command(resume={"decisions": [decision]})
                continue
            messages = result.value["messages"]
            done = (
                tool_results(messages, "finalize_dispatch")
                or tool_results(messages, "analyze_existing_plan")
                or case.get("decline")
                and approvals
            )
            if (
                (done and len(tool_results(messages, "finalize_dispatch")) >= case.get("legs", 1))
                or (case.get("decline") and approvals)
                or case["expect"] == "existing"
                and done
                or replies >= 2
            ):
                break
            replies += 1
            payload = {"messages": [{"role": "user", "content": FOLLOW_UP}]}
    except Exception as exc:  # recorded per case
        error = f"{type(exc).__name__}: {exc}"[:400]
        messages = []
    messages = messages if not error else []
    generations = tool_results(messages, "generate_in_simbrief")
    finals = tool_results(messages, "finalize_dispatch") + tool_results(
        messages, "analyze_existing_plan"
    )
    final = finals[-1] if finals else {}
    thrust = (final.get("thrust") or {}).get("status")
    checks = {
        "no_error": error is None,
        "retained_legs": len(finals) >= case.get("legs", 1)
        if case["expect"] == "generated"
        else True,
        "no_infeasible_flight": all(
            (f.get("feasibility") or {}).get("status") != "infeasible" for f in finals
        ),
        "outcome": {
            "generated": bool(generations)
            and generations[-1].get("status") == "generated"
            and final.get("status") == "complete",
            "declined": approvals > 0 and not generations,
            "existing": not generations and final.get("status") == "complete",
            "any": True,
        }[case["expect"]],
        "briefing_leads_with_spawn_and_thrust": not final
        or final.get("briefing_markdown", "").startswith("**SPAWN:**"),
        "thrust": case["thrust"] == "any"
        or (case["thrust"] == "estimated" and thrust == "estimated")
        or (case["thrust"] == "unavailable" and thrust not in (None, "estimated")),
        "calibrated": not case.get("calibrated")
        or "target_n1" in ((final.get("thrust") or {}).get("data") or {}),
    }
    return {
        "id": case["id"],
        "seconds": round(time.time() - started, 1),
        "approvals": approvals,
        "generation": [
            {k: g.get(k) for k in ("status", "session", "final_url", "prompts", "mismatched")}
            for g in generations
        ],
        "final_status": final.get("status"),
        "briefing": final.get("briefing_markdown"),
        "thrust_status": thrust,
        "last_reply": messages[-1].text[:600] if messages else None,
        "error": error,
        "aeroapi_result_sets": flights.usage["result_sets"] - before["result_sets"],
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default="")
    parser.add_argument(
        "--live", action="store_true", help="Authorize live SimBrief/Browserbase E2E"
    )
    parser.add_argument("--budget-usd", default="1.00", help="FlightAware-only batch ceiling")
    args = parser.parse_args()
    if not args.live or not args.ids:
        parser.error("E2E writes real plans: requires --live and explicit --ids")
    data = FlightData("live", args.budget_usd)
    cases = [c for c in CASES if not args.ids or c["id"] in args.ids.split(",")]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    experiment = f"e2e-{stamp}"
    tracing = export_tracing_settings()
    out = ROOT / "artifacts" / "evals" / experiment
    out.mkdir(parents=True, exist_ok=True)
    print(f"experiment {experiment}; LangSmith tracing {'on' if tracing else 'off'}", flush=True)
    passed = 0
    with open(out / "results.jsonl", "w") as handle:
        for case in cases:
            before_cost = data.charged
            with data.case(out / "recordings" / f"{case['id']}.json"):
                run = run_case(case, experiment)
            run["aeroapi_usd"] = (data.charged - before_cost) / 1000
            run["aeroapi_budget_blocked"] = data.budget_blocked
            handle.write(json.dumps(run) + "\n")
            handle.flush()
            failed = [k for k, v in run["checks"].items() if not v]
            passed += not failed
            sessions = [g["session"] for g in run["generation"] if g.get("session")]
            print(
                f"{case['id']} {'PASS' if not failed else 'FAIL ' + ','.join(failed)} "
                f"({run['seconds']}s, gen={[g['status'] for g in run['generation']]}, "
                f"final={run['final_status']}, thrust={run['thrust_status']}) {sessions}",
                flush=True,
            )
            if data.budget_blocked:
                break
    print(
        json.dumps({"experiment": experiment, "passed": passed, "out": str(out), **data.report()})
    )


if __name__ == "__main__":
    main()
