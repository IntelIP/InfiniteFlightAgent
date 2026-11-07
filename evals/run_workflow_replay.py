"""Real-model workflow regression with controlled provider responses, $0 FlightAware/Browserbase.

Uses existing ChatGPT-plan credentials. The real agent, approval middleware, workflow, parser,
Store and briefing renderer run. FlightAware and SimBrief responses are simulated; this is
not live-provider or simulator evidence. No remote state is written except LangSmith traces.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ifdispatcher import agent, flights, operations, workflow
from ifdispatcher.config import export_tracing_settings
from ifdispatcher.core import Store

ROOT = Path(__file__).resolve().parents[1]


def run_scenario(case: str, fail_first: bool = False, infeasible: bool = False) -> dict:
    generated = {}
    attempts = []
    approvals = []
    transcript = []

    def generate(fields, click, shots_dir, before_click=None):
        attempts.append(dict(fields))
        if fail_first and len(attempts) == 1:
            return {
                "status": "fill_mismatch",
                "mismatched": {"pax": {"want": "4", "got": "0"}},
                "reason": "Transient form readback; no Generate click occurred",
            }
        if before_click:
            before_click()
        raw = json.loads(
            (ROOT / "docs/research/evidence/simbrief-b38m-parser-fixture.json").read_text()
        )
        raw["origin"]["icao_code"] = fields["origin"]
        raw["destination"]["icao_code"] = fields["destination"]
        raw["aircraft"].update(icao_code="A20N", engines="LEAP-1A26", internal_id="A20N")
        selected = raw["tlr"]["takeoff"]["conditions"]["planned_runway"]
        for runway in raw["tlr"]["takeoff"]["runway"]:
            if runway["identifier"] == selected:
                runway.update(thrust_setting="FLEX", flex_temperature="50")
        raw["params"]["time_generated"] = datetime.now(timezone.utc).isoformat()
        raw["times"].update(
            sched_out=fields["departure_utc"], est_in="2026-11-08T14:00:00Z", est_block="02:00:00"
        )
        raw["weights"]["pax_count"] = str(fields.get("passengers") or 4)
        raw["fuel"] = dict(
            plan_ramp="7000",
            plan_takeoff="6800",
            min_takeoff="6000",
            plan_landing="2000",
            max_tanks="19117",
            reserve="785",
            alternate_burn="1000",
        )
        raw["general"] = {
            "flight_number": fields["callsign"],
            "initial_altitude": "36000",
            "route_distance": "500",
            "route": "DCT",
        }
        if infeasible:
            raw["fuel"].update(
                plan_ramp="20503", plan_takeoff="20273", min_takeoff="31642", plan_landing="-7101"
            )
            raw["general"]["sys_rmk"] = ["WARNING: FLIGHT EXCEEDS AIRCRAFT RANGE"]
        generated["body"] = json.dumps(raw).encode()
        return {"status": "generated", "session": "controlled-provider-response"}

    def airport(code):
        return {"KIAD": "Dulles", "KEWR": "Newark", "KLAX": "Los Angeles", "NZAA": "Auckland"}.get(
            code, code
        )

    def no_provider(*a, **k):
        raise AssertionError("Workflow replay must not call a live flight or browser provider")

    with (
        tempfile.TemporaryDirectory(prefix="ifd-workflow-replay-") as directory,
        patch.dict(os.environ, {"IFD_DATA_DIR": directory}),
        patch.object(workflow, "_store", lambda: Store(Path(directory))),
        patch.object(operations, "open_store", lambda: Store(Path(directory))),
        patch.object(flights, "_get", no_provider),
        patch.object(flights, "airport_name", airport),
        patch.object(flights, "airport_elevation", lambda _: 312),
        patch.object(flights, "airport_timezone", lambda _: "UTC"),
        patch.object(workflow.simbrief_browser, "generate", generate),
        patch.object(workflow.simbrief_browser, "airframes", no_provider),
        patch.object(workflow, "fetch_sync", lambda *a, **k: generated["body"]),
        patch.object(workflow.artifacts, "upload", lambda *a, **k: []),
    ):
        graph = agent.build_agent(checkpointer=InMemorySaver())
        config = {
            "configurable": {"thread_id": case},
            "tags": ["workflow-replay", case],
            "metadata": {"provider_mode": "controlled", "case_id": case},
        }
        route = "KLAX to NZAA" if infeasible else "KIAD to KEWR"
        prompt = f"Plan a private flight {route} on November 8, 2026 at 12:00 UTC in A20N, 4 passengers, callsign N320HD, KGS. Use the standard SimBrief A20N profile and its default route. Set it up now; I will approve in the approval prompt."
        payload = {"messages": [{"role": "user", "content": prompt}]}
        result = None
        for _ in range(5):
            result = graph.invoke(payload, config=config, version="v2")
            if result.interrupts:
                approvals.append(result.interrupts[0].value)
                payload = Command(resume={"decisions": [{"type": "approve"}]})
                continue
            if generated:
                break
            text = result.value["messages"][-1].text
            transcript.append(text)
            payload = {
                "messages": [
                    {
                        "role": "user",
                        "content": "All required inputs are in my request. Please prepare that exact private flight.",
                    }
                ]
            }
        messages = result.value["messages"]
        tools = [(m.name, json.loads(m.content)) for m in messages if m.type == "tool"]
        finals = [o for name, o in tools if name == "finalize_dispatch"]
        checks = {
            "approval_observed": bool(approvals),
            "plan_finalized": bool(finals),
            "one_generation_click": len(
                [x for name, x in tools if name == "generate_in_simbrief" and x.get("clicked")]
            )
            == 1,
            "expected_attempts": len(attempts) == (2 if fail_first else 1),
        }
        final = finals[-1] if finals else {}
        if infeasible:
            checks["infeasibility_reaches_user"] = (
                "FLIGHT FEASIBILITY: INFEASIBLE" in messages[-1].text
            )
            checks["thrust_withheld"] = "withheld" in messages[-1].text
        else:
            checks["calibration_guidance"] = (
                final.get("calibration", {}).get("status") == "reading_needed"
            )
            follow = graph.invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": "My observed full-throttle N1 in Infinite Flight on this runway with those same conditions is 92%. The simulator version is 26.3. Please update the N1 target for this saved plan.",
                        }
                    ]
                },
                config=config,
                version="v2",
            )
            outputs = [
                json.loads(m.content)
                for m in follow.value["messages"]
                if m.type == "tool" and m.name == "finalize_dispatch"
            ]
            checks["calibrated_target"] = bool(
                outputs
                and outputs[-1].get("thrust", {}).get("data", {}).get("calibration_full_thrust_n1")
                == 92
            )
            checks["no_regeneration_for_calibration"] = len(attempts) == (2 if fail_first else 1)
            transcript.append(follow.value["messages"][-1].text)
        transcript.insert(0, messages[-1].text)
        return {
            "case": case,
            "checks": checks,
            "passed": all(checks.values()),
            "attempts": len(attempts),
            "provider_mode": "controlled",
            "flightaware_usd": 0,
            "browserbase_sessions": 0,
            "transcript": transcript,
        }


def main():
    export_tracing_settings()
    results = []
    for case, retry, invalid in [
        ("retry-and-calibration", True, False),
        ("range-warning", False, True),
    ]:
        result = run_scenario(case, retry, invalid)
        results.append(result)
        print(json.dumps({k: v for k, v in result.items() if k != "transcript"}), flush=True)
    directory = ROOT / "artifacts/private"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "workflow-replay.json").write_text(json.dumps(results, indent=2) + "\n")
    raise SystemExit(0 if all(r["passed"] for r in results) else 1)


if __name__ == "__main__":
    main()
