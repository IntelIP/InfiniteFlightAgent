"""Evaluate conversation through dispatch approval, with FlightAware replay by default.

    uv run python evals/run_eval.py --ids SYNTH-001
    uv run python evals/run_eval.py --dataset evals/fixtures/synthetic_cases.jsonl
    uv run python evals/run_eval.py --dataset evals/dispatch_prompts.jsonl --live --ids IFD-001 --budget-usd 1.00

Replay still uses ChatGPT plan usage; it makes no FlightAware calls. Missing fixtures
invalidate a case and never fall back to live. Live mode records responses for reuse.
"""

import argparse
import json
import os
import random
import re
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from flight_data import FlightData

from langgraph.checkpoint.memory import InMemorySaver

from ifdispatcher import flights, workflow
from ifdispatcher.core import Store
from ifdispatcher.agent import build_agent
from ifdispatcher.config import export_tracing_settings
from ifdispatcher.siwc import chatgpt_model

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "fixtures" / "synthetic_cases.jsonl"
RESEARCH = {
    "find_route_flights": "search_route",
    "get_flight_by_number": "lookup_flight_number",
    "find_airport_departures": "airport_departures",
}
TOPIC_WORDS = {
    "origin": ["from", "depart", "starting", "leave from", "origin", "did you mean", "which"],
    "destination": [
        "where",
        "destination",
        "headed",
        "fly to",
        "did you mean",
        "which",
        "suggest",
        "airport",
    ],
    "date": ["date", "when", "day"],
    "time": ["time", "when", "morning", "evening"],
    "airline": ["airline", "carrier"],
    "aircraft": [
        "aircraft",
        "plane",
        "type",
        "airframe",
        "a20n",
        "a21n",
        "b38m",
        "neo",
        "737",
        "a320",
        "a321",
    ],
    "engine_or_livery": ["engine", "livery", "pw", "leap"],
    "private_or_airline": ["private", "airline", "real flight", "scheduled"],
    "passengers_or_load": ["passenger", "pax", "load", "payload"],
}
LIMIT_WORDS = [
    "2 days",
    "two days",
    "too far",
    "far ahead",
    "not available",
    "aren't available",
    "isn't available",
    "no live",
    "window",
    "can't see",
    "coverage",
    "outside",
    "only goes back",
    "already passed",
]
REQUEST = re.compile(
    r"\b(tell me|give me|let me know|please (confirm|provide|share|choose)|i'?ll (also )?need|i need|confirm)\b",
    re.I,
)
FLIGHT_NO = re.compile(r"\b(?:[A-Z]{2}|[A-Z]\d|\d[A-Z])\d{1,4}\b")


def simulated_reply(case: dict, asked: int) -> str:
    answers = {k: v for k, v in case["followups"].items() if k != "approve_dispatch"}
    if asked == 0 and answers:
        return "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in answers.items())
    if asked <= 1:
        return "That's everything I know. Go with your best suggestion and set it up."
    return "Yes, go ahead."


def _run_case(case: dict, model, max_turns: int, experiment: str) -> dict:
    agent = build_agent(model=model, checkpointer=InMemorySaver())
    config = {
        "configurable": {"thread_id": f"{experiment}-{case['id']}"},
        "run_name": f"{case['id']} {case['category']}",
        "tags": ["eval", experiment, case["category"]],
        "metadata": {
            "case_id": case["id"],
            "category": case["category"],
            "experiment": experiment,
            "flight_data_mode": case.get("_flight_data_mode", "replay"),
        },
    }
    before = dict(flights.usage)
    transcript, dispatches, turn_tools = [], [], []
    payload = {"messages": [{"role": "user", "content": case["prompt"]}]}
    asked, seen, error, started = 0, 0, None, time.time()
    try:
        for _ in range(max_turns * 3):
            result = agent.invoke(payload, config=config, version="v2")
            messages = result.value["messages"]
            new = messages[seen:]
            seen = len(messages)
            calls = [c for m in new for c in (getattr(m, "tool_calls", None) or [])]
            turn_tools.append([c["name"] for c in calls])
            call_args = {c["id"]: c["args"] for c in calls}
            for m in new:
                if m.type == "tool":
                    transcript.append(
                        {
                            "role": "tool",
                            "name": m.name,
                            "text": str(m.content),
                            "args": call_args.get(m.tool_call_id),
                        }
                    )
                elif m.type == "ai" and m.text:
                    transcript.append({"role": "assistant", "text": m.text})
            if result.interrupts:
                # Stop at the approval: approving would generate a real SimBrief plan.
                for request in result.interrupts[0].value["action_requests"]:
                    dispatches.append({**request["args"], "before_user_reply": asked == 0})
                    transcript.append({"role": "approval", "text": request.get("description", "")})
                break
            if dispatches or asked >= max_turns:
                break
            reply = simulated_reply(case, asked)
            transcript.append({"role": "user", "text": reply})
            payload = {"messages": [{"role": "user", "content": reply}]}
            asked += 1
    except Exception as exc:  # recorded per case; the run continues
        error = f"{type(exc).__name__}: {exc}"[:500]
    return {
        "id": case["id"],
        "category": case["category"],
        "prompt": case["prompt"],
        "seconds": round(time.time() - started, 1),
        "user_replies": asked,
        "turn_tools": turn_tools,
        "dispatches": dispatches,
        "transcript": transcript,
        "error": error,
        "aeroapi_result_sets": flights.usage["result_sets"] - before["result_sets"],
        "aeroapi_usd": (flights.usage["cost_milliusd"] - before["cost_milliusd"]) / 1000,
        "aeroapi_cache_hits": flights.usage["cache_hits"] - before["cache_hits"],
    }


def run_case(
    case: dict,
    model,
    max_turns: int,
    experiment: str,
    flight_data: FlightData | None = None,
    fixture: Path | None = None,
) -> dict:
    data = flight_data or FlightData()
    fixture = fixture or ROOT / case.get("fixture", f"evals/fixtures/recorded/{case['id']}.json")
    before = data.report()
    run = {
        "id": case["id"],
        "category": case["category"],
        "prompt": case["prompt"],
        "seconds": 0,
        "user_replies": 0,
        "turn_tools": [],
        "dispatches": [],
        "transcript": [],
        "error": None,
        "aeroapi_result_sets": 0,
        "aeroapi_cache_hits": 0,
    }

    def blocked(*args, **kwargs):
        raise ValueError("eval_scope: SimBrief actions are disabled in research evaluations")

    try:
        with (
            tempfile.TemporaryDirectory(prefix="ifd-eval-") as directory,
            patch.dict(os.environ, {"IFD_DATA_DIR": directory}),
            data.case(fixture),
            patch.object(workflow, "_store", lambda: Store(Path(os.environ["IFD_DATA_DIR"]))),
            patch.object(workflow, "generate_plan", blocked),
            patch.object(workflow, "finalize_dispatch", blocked),
            patch.object(workflow, "analyze_existing_plan", blocked),
        ):
            run = _run_case({**case, "_flight_data_mode": data.mode}, model, max_turns, experiment)
    except (OSError, ValueError) as exc:
        run["error"] = f"{type(exc).__name__}: {exc}"
    after = data.report()
    misses = after["fixture_misses"][len(before["fixture_misses"]) :]
    run.update(
        flight_data_mode=data.mode,
        fixture_kind=data.fixture_kind,
        fixture_clock=data.fixture_clock,
        fixture=str(fixture),
        fixture_misses=misses,
        aeroapi_usd=round(after["aeroapi_usd"] - before["aeroapi_usd"], 6),
        aeroapi_held_usd=round(after["aeroapi_held_usd"] - before["aeroapi_held_usd"], 6),
        aeroapi_calls=after["aeroapi_calls"][len(before["aeroapi_calls"]) :],
        replay_hits=after["replay_hits"] - before["replay_hits"],
        invalid=bool(misses or run["error"] or data.budget_blocked),
    )
    if misses:
        run["error"] = "fixture_miss: evaluation environment lacks requested data"
    if data.budget_blocked:
        run["error"] = "aeroapi_budget_exceeded: batch stopped"
    return run


def grade(case: dict, run: dict) -> dict[str, bool | None]:
    exp = case["expected"]
    first_tools = run["turn_tools"][0] if run["turn_tools"] else []
    first_text = next((t["text"] for t in run["transcript"] if t["role"] == "assistant"), "")
    first_text = first_text.replace("\u2019", "'")
    first_questions = " ".join(
        s for s in re.split(r"(?<=[?.!])\s+", first_text) if "?" in s or REQUEST.search(s)
    )
    research = [RESEARCH[t] for t in first_tools if t in RESEARCH]
    dispatched_first = any(d["before_user_reply"] for d in run["dispatches"])
    checks: dict[str, bool | None] = {"no_error": run["error"] is None}

    action = exp["first_action"]
    required = [t for t in exp["clarify_topics"] if t != "passengers_or_load"]
    if action == "ask_clarification" and not required:
        checks["first_action"] = bool(first_questions) or bool(run["dispatches"])
    elif action == "ask_clarification":
        checks["first_action"] = bool(first_questions) and not dispatched_first
    elif action == "explain_limitation":
        checks["first_action"] = not dispatched_first and any(
            w in first_text.lower() for w in LIMIT_WORDS
        )
    else:  # any research tool may find the route (e.g. a departures board with destination)
        checks["first_action"] = bool(research) or (
            action == "search_route" and bool(first_questions)
        )

    # Optional: SimBrief defaults the load; the agent need not block on it.
    topics = [t for t in exp["clarify_topics"] if t != "passengers_or_load"]
    if topics:
        # Asked in any turn before dispatch, or settled by offering concrete choices.
        said_all = " ".join(t["text"] for t in run["transcript"] if t["role"] == "assistant")
        said_all = re.sub(  # D.C. / a.m. / U.S. -> DC / am / US so sentences split correctly
            r"\b(?:[A-Za-z]\.){2,}", lambda m: m.group(0).replace(".", ""), said_all
        )
        q = " ".join(
            s for s in re.split(r"(?<=[?.!])\s+", said_all) if "?" in s or REQUEST.search(s)
        ).lower()
        offered = bool(
            re.search(r"which (flight|one|option|of these|would you)|prefer|choose|pick|go with", q)
            or re.search(r"how about|try |a few ideas|options?:", said_all.lower())
        )
        choice_settles = {"date", "time", "airline", "origin", "destination", "private_or_airline"}
        checks["clarify_coverage"] = all(
            any(w in q for w in TOPIC_WORDS[t]) or (offered and t in choice_settles) for t in topics
        )
    else:
        checks["clarify_coverage"] = None

    if run["dispatches"]:
        legs = [
            (d.get("origin", "").upper(), d.get("destination", "").upper())
            for d in run["dispatches"]
        ]
        ok = True
        for i, (origin, dest) in enumerate(legs):
            if i >= len(exp["legs"]):
                ok = False
                break
            want = exp["legs"][i]
            ok &= want["origin"] in (None, origin) and want["destination"] in (None, dest)
        checks["legs_match"] = ok
    else:
        checks["legs_match"] = None

    tool_text = " ".join(t["text"] for t in run["transcript"] if t["role"] in ("tool", "user"))
    said = " ".join(t["text"] for t in run["transcript"] if t["role"] == "assistant")
    said = said.replace("\u2019", "'")  # models write curly apostrophes: isn’t -> isn't
    known = set(FLIGHT_NO.findall(tool_text + " " + case["prompt"]))
    known |= {exp["aircraft_icao"] or ""} | {d.get("sim_aircraft") or "" for d in run["dispatches"]}
    invented = {n for n in FLIGHT_NO.findall(said) if n not in known}
    # ICAO aircraft type designators, not flight numbers: A380 B738 A21N B38M C750 E170 E75L CRJ7
    aircraft_name = re.compile(
        r"[ABCE]\d{3}|[ABE]\d{2}[A-Z]|CRJ\d|DH8[A-D]|AT7\d|CL[36]\d|GLF\d|LJ\d{2}|PC12|TBM\d"
    )
    invented = {n for n in invented if not aircraft_name.fullmatch(n)}
    invented = {n for n in invented if not re.fullmatch(r"N\d{1,5}[A-Z]{0,2}", n)}  # N-numbers
    checks["no_invented_flight_numbers"] = not {n for n in invented if not n[:1].isdigit()}

    # Disclosed before approval: in chat, or in the approval summary every client shows.
    approval = " ".join(t["text"] for t in run["transcript"] if t["role"] == "approval")
    said = f"{said} {approval}"
    if exp["thrust_supported"] is False and run["dispatches"]:
        checks["unsupported_thrust_disclosed"] = bool(
            re.search(
                r"(thrust|n1)[^.]{0,80}(unavailable|not (be )?(supported|available)|"
                r"(isn't|aren't|won't be) (supported|available)|"
                r"can't|only supported)",
                said,
                re.I,
            )
            or re.search(r"(unavailable|not supported)[^.]{0,80}(thrust|n1)", said, re.I)
        )
    else:
        checks["unsupported_thrust_disclosed"] = None

    checks["did_not_assume_date"] = (
        not dispatched_first if "date" in exp["clarify_topics"] else None
    )
    if exp["real_flight_expected"] is False and run["dispatches"]:
        checks["private_handled"] = all(
            not d.get("fa_flight_id") and d.get("private_callsign") for d in run["dispatches"]
        )
    else:
        checks["private_handled"] = None
    if exp.get("disallow_dispatch"):
        checks["no_dispatch_without_operating_flight"] = not run["dispatches"]
    observed = {}
    for item in run["transcript"]:
        if item["role"] != "tool":
            continue
        try:
            envelope = json.loads(item["text"])
        except (ValueError, TypeError):
            continue
        rows = envelope.get("data") if isinstance(envelope, dict) else None
        rows = [rows] if isinstance(rows, dict) else rows
        for flight in rows if isinstance(rows, list) else []:
            if isinstance(flight, dict) and flight.get("fa_flight_id"):
                observed[flight["fa_flight_id"]] = flight
    checks["dispatch_flight_grounded"] = (
        all(
            bool(observed.get(d.get("fa_flight_id")))
            and not observed[d["fa_flight_id"]].get("cancelled")
            if d.get("fa_flight_id")
            else exp["real_flight_expected"] is not True
            for d in run["dispatches"]
        )
        if run["dispatches"]
        else None
    )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default="")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--live", action="store_true", help="Explicitly enable paid FlightAware")
    parser.add_argument("--budget-usd", default="1.00", help="Whole-batch FlightAware ceiling")
    parser.add_argument("--fixture-dir", type=Path, default=ROOT / "evals/fixtures/recorded")
    parser.add_argument("--per-category", type=int, default=0)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--effort", default="low")
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    if args.max_turns < 1 or args.per_category < 0:
        parser.error("max-turns must be positive; per-category must be nonnegative")

    cases = [json.loads(line) for line in args.dataset.read_text().splitlines() if line.strip()]
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    elif args.per_category:
        by_cat = defaultdict(list)
        for c in cases:
            by_cat[c["category"]].append(c)
        rng = random.Random(args.seed)
        cases = [c for cat in sorted(by_cat) for c in rng.sample(by_cat[cat], args.per_category)]

    if args.live and not (args.ids or args.per_category):
        parser.error(
            "live mode requires --ids or --per-category; full live suites are not implicit"
        )
    if not cases:
        parser.error("no matching cases")
    if args.live and any(c.get("fixture") for c in cases):
        parser.error("synthetic/fixture-specific cases must not be sent to live providers")
    data = FlightData("live" if args.live else "replay", args.budget_usd)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    experiment = f"eval-{data.mode}-{stamp}"
    tracing = export_tracing_settings()
    print(f"experiment {experiment}; LangSmith tracing {'on' if tracing else 'off'}", flush=True)
    out = ROOT / "artifacts" / "evals" / stamp
    out.mkdir(parents=True, exist_ok=True)
    model = chatgpt_model(args.model, args.effort)
    totals: dict[str, list] = defaultdict(list)
    by_category: dict[str, list] = defaultdict(list)
    with open(out / "results.jsonl", "w") as handle:
        for n, case in enumerate(cases, 1):
            fixture = (
                (out / "recordings" / f"{case['id']}.json")
                if args.live
                else (
                    ROOT / case["fixture"]
                    if case.get("fixture")
                    else args.fixture_dir / f"{case['id']}.json"
                )
            )
            run = run_case(case, model, args.max_turns, experiment, data, fixture)
            run["checks"] = grade(case, run)
            handle.write(json.dumps(run) + "\n")
            handle.flush()
            scored = {k: v for k, v in run["checks"].items() if v is not None}
            passed = all(scored.values())
            if not run["invalid"]:
                by_category[case["category"]].append(passed)
                for k, v in scored.items():
                    totals[k].append(v)
            failed = [k for k, v in scored.items() if not v]
            print(
                f"[{n}/{len(cases)}] {case['id']} {case['category']:<22} "
                f"{'PASS' if passed else 'FAIL ' + ','.join(failed)} "
                f"({run['seconds']}s, ${run['aeroapi_usd']:.3f}, invalid={run['invalid']})",
                flush=True,
            )

            if data.budget_blocked:
                break

    runs = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
    summary = {
        "experiment": experiment,
        **data.report(),
        "langsmith_tracing": tracing,
        "model": args.model,
        "effort": args.effort,
        "cases": len(runs),
        "valid_cases": sum(not r["invalid"] for r in runs),
        "invalid_cases": [r["id"] for r in runs if r["invalid"]],
        "case_pass_rate": (
            round(
                sum(sum(v) for v in by_category.values())
                / sum(len(v) for v in by_category.values()),
                3,
            )
            if any(by_category.values())
            else None
        ),
        "checks": {k: f"{sum(v)}/{len(v)}" for k, v in totals.items()},
        "by_category": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_category.items())},
        "median_seconds": sorted(r["seconds"] for r in runs)[len(runs) // 2] if runs else None,
        "aeroapi_result_sets": sum(r["aeroapi_result_sets"] for r in runs),
        "aeroapi_usd": round(sum(r["aeroapi_usd"] for r in runs), 3),
        "errors": [r["id"] for r in runs if r["error"]],
        "results": str(out / "results.jsonl"),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    if summary["invalid_cases"] or any(
        not all(v for v in r["checks"].values() if v is not None) for r in runs
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
