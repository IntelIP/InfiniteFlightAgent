"""Whole-workflow baseline: scripted model by default; controlled providers in every run.

No real FlightAware/Browserbase, production storage, artifact uploads or ambient tracing.
Real-model replay and publishing saved results to LangSmith require separate explicit flags.
"""

import argparse
import json
import os
import tempfile
import threading
import time
import sqlite3
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from langsmith import tracing_context

from ifdispatcher import (
    agent,
    browser_budget,
    core,
    flights,
    observability,
    operations,
    progress,
    remote,
    workflow,
)
from ifdispatcher.core import Store
from workflow_evaluations import (
    MANIFEST,
    ROOT,
    VERIFIER_VERSION,
    canonical,
    compare,
    key,
    load_manifest,
    sha256,
    source_identity,
    upload_experiment,
    verify,
)


class ScriptedModel(GenericFakeChatModel):
    """Fixed AI messages, matching the existing real-graph regression test pattern."""

    def bind_tools(self, tools, **kwargs):
        return self


class Measurements(BaseCallbackHandler):
    def __init__(self):
        self.started = {}
        self.stages = []

    def on_tool_start(self, serialized, _input_str, *, run_id, **kwargs):
        self.started[run_id] = (serialized.get("name"), time.perf_counter())

    def on_tool_end(self, output, *, run_id, **kwargs):
        self.finish(run_id, False)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self.finish(run_id, True)

    def finish(self, run_id, failed):
        if run_id in self.started:
            name, start = self.started.pop(run_id)
            self.stages.append(
                {"stage": name, "seconds": time.perf_counter() - start, "error": failed}
            )


def scripted_messages(case):
    if "script" in case:
        return [
            AIMessage(step["text"])
            if "text" in step
            else AIMessage(
                "",
                tool_calls=[{"id": f"case-call-{i}", "name": step["tool"], "args": step["args"]}],
            )
            for i, step in enumerate(case["script"])
        ]
    messages = []

    def call(name, args):
        messages.append(
            AIMessage("", tool_calls=[{"id": f"call-{len(messages)}", "name": name, "args": args}])
        )

    for leg in case["legs"]:
        target = {name: leg[name] for name in ("trip", "leg", "revision")}
        call("dispatch_flight", leg)
        if case["scenario"] == "decline":
            messages.append(AIMessage("Dispatch declined. No plan was generated."))
            break
        call("generate_in_simbrief", target)
        if case["scenario"] == "provider_failure":
            messages.append(
                AIMessage(
                    "Browser provider quota exhausted. No Generate click occurred. Restore quota before trying again; the dispatch inputs are retained."
                )
            )
            break
        if case["scenario"] == "retry_duplicate":
            call("generate_in_simbrief", target)  # successful retry after the pre-click mismatch
            call("generate_in_simbrief", target)  # deliberately tests server-side duplicate fence
        call("finalize_dispatch", target)
        if case["scenario"] == "retry_duplicate":
            call("finalize_dispatch", {**target, "full_thrust_n1": 92, "simulator_version": "26.3"})
        if case["scenario"] == "revision_recovery":
            call(
                "revise_dispatch",
                {
                    "trip": leg["trip"],
                    "leg": leg["leg"],
                    "base_revision": 1,
                    "changes": {"alternate": "KBWI", "cruise_altitude": "FL350"},
                },
            )
    if case["scenario"] not in {"decline", "provider_failure"}:
        reply = {
            "infeasible": "The generated flight is infeasible. Takeoff thrust is withheld; revise the plan first.",
            "unsupported": "The briefing is saved. Takeoff thrust is unavailable for this aircraft.",
            "revision_recovery": "Alternate and cruise altitude changes are unsupported. The original saved plan remains unchanged; please choose supported changes or edit those fields manually.",
        }.get(
            case["scenario"],
            "The saved briefing is ready. Spawn and thrust guidance are in the retained briefing.",
        )
        messages.append(AIMessage(reply))
    return messages


def controlled_ofp(source, fields, clock, infeasible=False):
    """v1 fixture transformation, deliberately synthetic and not an actual complete OFP."""
    raw = json.loads(source)
    raw["origin"]["icao_code"] = fields["origin"]
    raw["destination"]["icao_code"] = fields["destination"]
    aircraft = fields["aircraft"]
    raw["aircraft"].update(
        icao_code=aircraft, engines="LEAP-1A26", internal_id=fields["airframe_id"]
    )
    selected = raw["tlr"]["takeoff"]["conditions"]["planned_runway"]
    for runway in raw["tlr"]["takeoff"]["runway"]:
        if runway["identifier"] == selected:
            runway.update(thrust_setting="FLEX", flex_temperature="50")
    raw["params"].update(
        time_generated=(clock + timedelta(seconds=1)).isoformat(), units=fields["units"].lower()
    )
    depart = datetime.fromisoformat(fields["departure_utc"].replace("Z", "+00:00"))
    raw["times"].update(
        sched_out=fields["departure_utc"],
        est_in=(depart + timedelta(hours=2)).isoformat(),
        est_block="02:00:00",
    )
    raw["weights"]["pax_count"] = str(fields.get("passengers"))
    raw["fuel"] = dict(
        plan_ramp="7000",
        plan_takeoff="6800",
        min_takeoff="6000",
        plan_landing="2000",
        max_tanks="19117",
        reserve="785",
        alternate_burn="1000",
    )
    raw["general"] = dict(
        flight_number=fields["callsign"],
        initial_altitude="36000",
        route_distance="500",
        route="DCT",
    )
    if infeasible:
        raw["fuel"].update(
            plan_ramp="20503", plan_takeoff="20273", min_takeoff="31642", plan_landing="-7101"
        )
        raw["general"]["sys_rmk"] = ["WARNING: FLIGHT EXCEEDS AIRCRAFT RANGE"]
    return json.dumps(raw).encode()


def read_state(store):
    rows = []
    for trip in store.trips():
        for leg, _, _ in store.trip_legs(trip):
            for request in store.revisions(trip, leg):
                ident = (trip, leg, request["revision"])
                row = {"request": request, "meta": store.read_meta(*ident), "snapshot": None}
                try:
                    row["snapshot"] = store.read(*ident)
                    row["raw"] = store.read_raw(*ident)
                    with store.connect() as db:
                        body = db.execute(
                            "SELECT raw FROM snapshots WHERE trip=? AND leg=? AND revision=?", ident
                        ).fetchone()[0]
                    row["computed_sha256"] = sha256(body)
                except ValueError:
                    pass
                rows.append(row)
    return rows


def run_case(case, manifest, model=None, max_turns=5, mcp_url=None):
    if Path(core.__file__).resolve().parent != ROOT / "src/ifdispatcher":
        raise ValueError(
            "application import targets a different checkout; set PYTHONPATH to this checkout's src"
        )
    clock = datetime.fromisoformat(manifest["clock_utc"].replace("Z", "+00:00"))

    class Clock(datetime):
        @classmethod
        def now(_cls, tz=None):
            return clock.astimezone(tz) if tz else clock.replace(tzinfo=None)

    measurement = Measurements()
    run = {
        "case_id": case["id"],
        "case_sha256": sha256(canonical(case)),
        "approvals": [],
        "clicks": [],
        "provider_attempts": [],
        "provider_plans": [],
        "observations": [],
        "tool_results": [],
        "transcript": [],
        "error": None,
        "invalid": False,
        "invalid_reasons": [],
        "final_reply": "",
        "state": [],
    }
    body = None
    approved = []
    messages = []
    clarification_turns = 0
    continuation_turns = 0
    turns = []
    source = (ROOT / manifest["fixture"]["path"]).read_bytes()
    control = case.get("control") or {}
    concurrent = []  # cancel_trip calls made by a concurrent client while a turn runs
    driver = None

    def mcp_call(name, args):
        output = driver.call(name, args)
        run.setdefault("mcp_outputs", []).append({"tool": name, "output": output})
        return output

    def cancel_during_turn():
        """Cancel from a second client mid-turn, then continue once the turn sees it."""
        if control.get("cancel_at") not in {"pre_click", "post_click"}:
            return
        caller = threading.Thread(
            target=mcp_call,
            args=("cancel_trip", {"thread_id": case["id"], "reason": "owner cancelled"}),
        )
        caller.start()
        concurrent.append(caller)
        deadline = time.monotonic() + 10
        while not (case["id"] in remote._controls and remote._controls[case["id"]].event.is_set()):
            if time.monotonic() > deadline:
                raise RuntimeError("controlled cancellation was not received")
            time.sleep(0.01)

    def blocked(*args, **kwargs):
        run["invalid"] = True
        run["invalid_reasons"].append("fixture/provider isolation lacks requested operation")
        raise RuntimeError("evaluation isolation: live provider access forbidden")

    def airframes(aircraft):
        options = manifest.get("airframe_options", {}).get(aircraft)
        if options is None:
            return blocked()
        return {
            "status": "ok",
            "aircraft": aircraft,
            "airframes": options,
            "note": "Controlled standard-profile fixture; no custom account profiles or simulator applicability established.",
        }

    def generate(fields, click, shots_dir, before_click=None):
        nonlocal body
        # Resolve the exact retained request rather than trusting a model-supplied tag.
        candidates = [
            row for row in read_state(store) if workflow._tag(*key(row["request"])) == fields["tag"]
        ]
        ident = key(candidates[0]["request"])
        run["provider_attempts"].append({"key": ident, "fields": dict(fields)})
        failure = case.get(
            "provider_failure", "quota" if case["scenario"] == "provider_failure" else None
        )
        if failure in {"quota", "concurrency", "auth", "transient"}:
            from browserbase import APIStatusError

            status, message = {
                "quota": (429, "quota exhausted"),
                "concurrency": (429, "concurrent sessions limit exceeded"),
                "auth": (401, "invalid API key"),
                "transient": (503, "service unavailable"),
            }[failure]
            raise APIStatusError(
                message,
                response=httpx.Response(
                    status, request=httpx.Request("POST", "https://controlled.invalid/sessions")
                ),
                body={"message": message},
            )
        if failure == "timeout_before_click":
            raise TimeoutError("controlled pre-click timeout")
        if control.get("cancel_at") == "pre_click":
            cancel_during_turn()
        if control.get("cancel_at") == "deadline_pre_click":
            # Real elapsed time past the configured turn deadline; no clock patching.
            time.sleep(float(control["deadline_seconds"]) + 0.5)
        if case["scenario"] == "retry_duplicate" and len(run["provider_attempts"]) == 1:
            return {
                "status": "fill_mismatch",
                "mismatched": {"pax": {"want": "4", "got": "0"}},
                "reason": "Controlled readback mismatch; no Generate click",
            }
        if before_click:
            before_click()
        run["clicks"].append({"key": ident, "approved": list(approved)})
        body = controlled_ofp(source, fields, clock, case["scenario"] == "infeasible")
        raw = json.loads(body)
        if fields.get("airline"):
            raw["general"].update(
                icao_airline=fields["airline"], flight_number=fields["flight_number"]
            )
        if case.get("no_performance"):
            raw.pop("tlr", None)
        route = case.get("retained_route", fields.get("route") or "JCOBY4 SWANN PHLBO4")
        if "route_evidence" in case:
            raw["general"]["route"] = route
            raw["navlog"] = {"fix": [{"ident": s} for s in case["route_evidence"]]}
        body = json.dumps(raw).encode()
        run["provider_plans"].append({"key": ident, "sha256": sha256(body), "fields": fields})
        if control.get("cancel_at") == "post_click":
            cancel_during_turn()
        if failure == "timeout_after_click":
            raise TimeoutError("controlled post-click timeout")
        return {
            "status": "generated",
            "session": "controlled-provider",
            **(
                {"values": {"route": fields.get("route") or route}}
                if "route_evidence" in case
                else {}
            ),
        }

    def observe():
        run["state"] = read_state(store)
        run["observations"].append(
            {
                "approved": list(approved),
                "request_keys": [key(row["request"]) for row in run["state"]],
                "click_keys": [click["key"] for click in run["clicks"]],
                "snapshot_hashes": [
                    (key(row["request"]), row["snapshot"]["raw_sha256"])
                    for row in run["state"]
                    if row["snapshot"]
                ],
            }
        )

    seen = set()

    def harvest(current):
        for message in messages:
            if message.id in seen:
                continue
            seen.add(message.id)
            run["transcript"].append(
                {
                    "type": message.type,
                    "name": getattr(message, "name", None),
                    "text": str(message.content),
                }
            )
            if message.type == "tool":
                try:
                    output = json.loads(message.content)
                except (TypeError, ValueError):
                    output = {"text": str(message.content)}
                run["tool_results"].append(
                    {
                        "name": message.name,
                        "output": output,
                        "status": getattr(message, "status", None),
                    }
                )

    events = []
    token = observability.meter.set(events)
    started = time.perf_counter()
    with (
        tempfile.TemporaryDirectory(prefix="ifd-workflow-eval-") as directory,
        ExitStack() as stack,
    ):
        store = Store(Path(directory))
        stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "IFD_DATA_DIR": directory,
                    "IFD_AIRPORT_CACHE_DIR": "disabled",
                    "IFD_INTERNAL_TOKEN": "controlled-workflow-replay-token",
                    "LANGSMITH_TRACING": "false",
                    **(
                        {"IFD_TURN_DEADLINE_SECONDS": str(control["deadline_seconds"])}
                        if "deadline_seconds" in control
                        else {}
                    ),
                },
            )
        )
        for module, name, replacement in (
            (workflow, "_store", lambda: store),
            (operations, "open_store", lambda: store),
            (core, "open_store", lambda: store),
            (browser_budget, "open_store", lambda: store),
            (flights, "_get", blocked),
            (flights, "airport_name", lambda code: f"Controlled airport {code}"),
            (flights, "airport_elevation", lambda _: 312),
            (
                flights,
                "airport_timezone",
                lambda code: case.get("airport_timezones", {}).get(code, "UTC"),
            ),
            (workflow.simbrief_browser, "generate", generate),
            (workflow.simbrief_browser, "airframes", airframes),
            (workflow, "fetch_sync", lambda *a, **k: body if body else blocked()),
            (core, "fetch_sync", blocked),
            (workflow.artifacts, "upload", lambda *a, **k: []),
            (observability, "write_feedback", lambda *a, **k: None),
            (workflow, "datetime", Clock),
            (core, "datetime", Clock),
            (flights, "datetime", Clock),
            (agent, "datetime", Clock),
            (operations, "datetime", Clock),
            (progress, "datetime", Clock),
            (remote, "paid_operations_enabled", lambda: True),
        ):
            stack.enter_context(patch.object(module, name, replacement))
        # Do not export .env tracing settings or send ambient traces; explicit upload is separate.
        stack.enter_context(tracing_context(enabled=False))
        try:
            if control and not mcp_url:
                run["invalid"] = True
                run["invalid_reasons"].append("trip-control case requires --mcp transport")
                run.update(verify(case, run))
                return run
            if case.get("airline_flight"):
                flight = case["airline_flight"]
                required = {
                    "flight_number",
                    "ident_icao",
                    "fa_flight_id",
                    "codeshares",
                    "times",
                    "origin",
                    "destination",
                    "departure_gate",
                    "departure_terminal",
                    "arrival_gate",
                    "aircraft_type",
                    "registration",
                    "note",
                }
                missing = sorted(required - flight.keys())
                missing += [
                    f"times.{field}"
                    for field in flights.TIME_FIELDS
                    if field not in flight.get("times", {})
                ]
                if missing:
                    run["invalid"] = True
                    run["invalid_reasons"].append(
                        "missing controlled flight fixture fields: " + ", ".join(missing)
                    )
                    run.update(verify(case, run))
                    return run

                def flight_get(path, params=None):
                    if (
                        path.startswith("/flights/")
                        or path
                        == f"/airports/{flight['origin']['icao']}/flights/to/{flight['destination']['icao']}"
                    ):
                        raw = {
                            "ident_iata": flight["flight_number"],
                            "ident_icao": flight["ident_icao"],
                            "fa_flight_id": flight["fa_flight_id"],
                            "codeshares_iata": flight["codeshares"],
                            "origin": {"code_icao": flight["origin"]["icao"], "timezone": "UTC"},
                            "destination": {
                                "code_icao": flight["destination"]["icao"],
                                "timezone": "UTC",
                            },
                            "gate_origin": flight["departure_gate"],
                            "gate_destination": flight["arrival_gate"],
                            "terminal_origin": flight["departure_terminal"],
                            "aircraft_type": flight["aircraft_type"],
                            **{k: v["utc"] for k, v in flight["times"].items()},
                        }
                        return {"flights": [raw], "num_pages": 1}
                    return blocked()

                stack.enter_context(patch.object(flights, "_get", flight_get))
                stack.enter_context(
                    patch.object(
                        flights,
                        "refresh_flight",
                        lambda _: {
                            "status": "ok",
                            "data": case["airline_flight"],
                            "sources": ["controlled flight fixture"],
                        },
                    )
                )
            selected_model = model or ScriptedModel(messages=iter(scripted_messages(case)))
            checkpoint = (
                SqliteSaver(
                    sqlite3.connect(
                        str(Path(directory) / "checkpoint.sqlite"), check_same_thread=False
                    )
                )
                if mcp_url
                else InMemorySaver()
            )
            if mcp_url:
                stack.callback(checkpoint.conn.close)
            graph = agent.build_agent(model=selected_model, checkpointer=checkpoint)
            driver = graph
            if mcp_url:
                from mcp_replay import MCPDriver

                driver = MCPDriver(mcp_url, graph, measurement, run)
                stack.enter_context(patch.object(remote, "_get_agent", lambda: driver))
                stack.enter_context(patch.object(remote, "_turns", {}))
            config = {
                "configurable": {"thread_id": case["id"]},
                "callbacks": [measurement],
                "tags": ["workflow-evaluation", case["id"]],
                "metadata": {"case_id": case["id"], "verifier_version": VERIFIER_VERSION},
            }
            payload = {"messages": [{"role": "user", "content": case["prompt"]}]}
            in_turn = False
            for _ in range(max_turns * 3):
                turn_start = time.perf_counter()
                in_turn = True
                result = driver.invoke(payload, config=config, version="v2")
                turns.append(
                    {
                        "stage": "approval_resume"
                        if isinstance(payload, Command)
                        else "conversation",
                        "seconds": time.perf_counter() - turn_start,
                    }
                )
                in_turn = False
                messages = result.value["messages"]
                harvest(messages)
                observe()
                if (
                    result.interrupts
                    and control.get("cancel_at") == "approval"
                    and len(run["approvals"]) == control.get("approval_index", 0)
                ):
                    # The owner stops at this approval instead of answering it.
                    pending = result.interrupts[0].value["action_requests"][0]
                    run["cancelled_approvals"] = [pending]
                    cancelled = mcp_call(
                        "cancel_trip", {"thread_id": case["id"], "reason": "owner cancelled"}
                    )
                    run["cancelled"] = cancelled["status"] == "cancelled"
                    mcp_call("approve_dispatch", {"thread_id": case["id"], "approve": True})
                    break
                if result.interrupts:
                    decisions = []
                    for interrupt in result.interrupts:
                        for request in interrupt.value["action_requests"]:
                            decision = "reject" if case["scenario"] == "decline" else "approve"
                            resolved = request["args"]
                            if request["name"] == "revise_dispatch":
                                resolved = operations.revision_inputs(**request["args"])
                            run["approvals"].append(
                                {**request, "decision": decision, "resolved_args": resolved}
                            )
                            decisions.append({"type": decision})
                            if decision == "approve":
                                approved.append(resolved)
                    payload = Command(resume={"decisions": decisions})
                    continue
                run["final_reply"] = messages[-1].text
                retained = sum(bool(row.get("snapshot")) for row in run["state"])
                if (
                    0 < retained < len(case["legs"])
                    and case["expected_outcome"] == "briefing_ready"
                    and continuation_turns < len(case["legs"])
                ):
                    # The production client shows a finished leg before requesting the
                    # next exact approval. Continuing a settled itinerary supplies no new
                    # flight inputs and is distinct from asking the user to clarify them.
                    continuation_turns += 1
                    payload = {
                        "messages": [
                            {
                                "role": "user",
                                "content": "Continue the same settled itinerary. Preserve every finished leg and revision. "
                                "Prepare the remaining leg or requested revision for its exact approval; "
                                "do not regenerate an existing revision.",
                            }
                        ]
                    }
                    continue
                followups = case.get("followups", [])
                if clarification_turns < len(followups):
                    content = followups[clarification_turns]
                elif run["state"] or case["scenario"] == "decline" or case.get("no_dispatch"):
                    break
                else:
                    content = "All required inputs are supplied above. Prepare that exact itinerary and use the approval prompt."
                if clarification_turns >= max_turns:
                    break
                clarification_turns += 1
                payload = {
                    "messages": [
                        {
                            "role": "user",
                            "content": content,
                        }
                    ]
                }
            if mcp_url:
                saved = driver.call("list_saved_trips", {"trip": case["legs"][0]["trip"]})
                run["mcp_saved"] = saved
                if case.get("restart"):
                    remote._turns.clear()
                    # Reconstruct both the graph and checkpoint connection from disk.
                    checkpoint.conn.close()
                    replacement = SqliteSaver(
                        sqlite3.connect(
                            str(Path(directory) / "checkpoint.sqlite"), check_same_thread=False
                        )
                    )
                    stack.callback(replacement.conn.close)
                    graph = agent.build_agent(model=selected_model, checkpointer=replacement)
                    driver.graph = graph
                    run["recovered"] = driver.call("conversation_status", {"thread_id": case["id"]})
                if control:
                    for caller in concurrent:
                        caller.join(timeout=remote.WAIT_SECONDS + 15)
                    mcp_call("turn_status", {"thread_id": case["id"]})
                    mcp_call("trip_progress", {"thread_id": case["id"]})
            observe()
        except Exception as exc:

            def describe(error):
                return {
                    "type": type(error).__name__,
                    "message": str(error)[:1000],
                    **(
                        {"causes": [describe(e) for e in error.exceptions]}
                        if isinstance(error, BaseExceptionGroup)
                        else {}
                    ),
                }

            run["error"] = describe(exc)
            if locals().get("in_turn"):
                turns.append({"stage": "turn_error", "seconds": time.perf_counter() - turn_start})
            if "graph" in locals():
                messages = graph.get_state(config).values.get("messages", messages)
                harvest(messages)
            observe()
        finally:
            observability.meter.reset(token)
    schema_errors = [
        t
        for t in run["tool_results"]
        if t["status"] == "error"
        and any(
            s in str(t["output"]).lower()
            for s in (
                "validation error",
                "validationerror",
                "invalid_tool_call",
                "unexpected keyword",
            )
        )
    ]
    calls = [call for message in messages for call in (getattr(message, "tool_calls", None) or [])]
    usage = [
        message.usage_metadata for message in messages if getattr(message, "usage_metadata", None)
    ]
    run["metrics"] = {
        "clarification_turns": clarification_turns,
        "continuation_turns": continuation_turns,
        "assistant_question_turns": sum(m.type == "ai" and "?" in m.text for m in messages),
        "tool_calls": len(calls),
        "tool_calls_by_name": dict(Counter(c["name"] for c in calls)),
        "tool_schema_errors": schema_errors,
        "stage_latency_s": measurement.stages,
        "turn_latency_s": turns,
        "elapsed_s": time.perf_counter() - started,
        "model_usage": usage or None,
        "model_cost_usd": None if model is not None else 0,
        "flightaware_requests": 0,
        "flightaware_usd": 0,
        "browserbase_sessions": 0,
        "browserbase_usd": 0,
        "provider_usage": events,
        "owner_ratings": None,
        "queue_latency_s": None,
        "browser_latency_s": None,
        "transport": "mcp-http" if mcp_url else "graph",
    }
    run["workflow"] = observability.summarize(messages, set())
    run.update(verify(case, run))
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--manifest", type=Path, default=MANIFEST)
    run_parser.add_argument("--ids", default="")
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--real-model", action="store_true")
    run_parser.add_argument(
        "--mcp", action="store_true", help="Use production MCP tools over loopback HTTP"
    )
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("baseline", type=Path)
    compare_parser.add_argument("candidate", type=Path)
    compare_parser.add_argument("--output", type=Path)
    upload_parser = commands.add_parser("upload")
    upload_parser.add_argument("run", type=Path)
    upload_parser.add_argument("--manifest", type=Path, default=MANIFEST)
    upload_parser.add_argument("--dataset-name", required=True)
    upload_parser.add_argument("--experiment-prefix", required=True)
    args = parser.parse_args()
    if args.command == "compare":
        result = compare(
            json.loads(args.baseline.read_text()), json.loads(args.candidate.read_text())
        )
        text = json.dumps(result, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text)
        print(text)
        raise SystemExit(
            int(
                bool(
                    result["compatibility_errors"]
                    or any(r["status"] != "matched" or r["regressions"] for r in result["cases"])
                )
            )
        )
    manifest = load_manifest(args.manifest)
    if args.command == "upload":
        from langsmith import Client

        # Explicit publication uses the project's existing LangSmith settings only here.
        from ifdispatcher.config import export_tracing_settings, setting

        export_tracing_settings()
        result = upload_experiment(
            json.loads(args.run.read_text()),
            manifest,
            Client(api_key=setting("LANGSMITH_API_KEY")),
            args.dataset_name,
            args.experiment_prefix,
        )
        print(
            json.dumps(
                {
                    "experiment_name": result.experiment_name,
                    "experiment_id": str(result.experiment_id),
                    "url": result.url,
                    "case_runs": [
                        {"case_id": row["run"].outputs.get("case_id"), "run_id": str(row["run"].id)}
                        for row in result
                    ],
                }
            )
        )
        return
    wanted = set(args.ids.split(",")) if args.ids else {c["id"] for c in manifest["cases"]}
    if not wanted <= {c["id"] for c in manifest["cases"]}:
        parser.error("unknown case IDs")
    model = None
    if args.real_model:
        from ifdispatcher.siwc import chatgpt_model

        model = chatgpt_model("gpt-6-luna", "low")
    identity = source_identity()
    harness_sha256 = sha256(
        canonical(
            {
                name: digest
                for name, digest in identity["source_files"].items()
                if name.startswith("evals/")
            }
        )
    )
    batch = {
        "suite_id": manifest["suite_id"],
        "suite_sha256": sha256(canonical(manifest)),
        "verifier_version": VERIFIER_VERSION,
        "fixture": manifest["fixture"],
        "fixture_clock": manifest["clock_utc"],
        "base_commit": manifest["base_commit"],
        "source": identity,
        "harness_sha256": harness_sha256,
        "evidence_mode": "real-model-replay" if model else "scripted-controlled",
        "model": "gpt-6-luna" if model else "scripted",
        "effort": "low" if model else None,
        "case_ids": [c["id"] for c in manifest["cases"] if c["id"] in wanted],
        "results": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "owner_ratings": None,
    }
    with ExitStack() as stack:
        mcp_url = None
        if args.mcp:
            from mcp_replay import MCPServer

            mcp_url = stack.enter_context(MCPServer()).url
        for case in manifest["cases"]:
            if case["id"] in wanted:
                result = run_case(case, manifest, model=model, mcp_url=mcp_url)
                batch["results"].append(result)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(batch, indent=2) + "\n")
                print(
                    json.dumps(
                        {
                            "case_id": case["id"],
                            "passed": result["passed"],
                            "invalid": result["invalid"],
                            "constraint_failures": result["constraint_failures"],
                        }
                    ),
                    flush=True,
                )
    raise SystemExit(int(any(r["invalid"] or not r["passed"] for r in batch["results"])))


if __name__ == "__main__":
    main()
