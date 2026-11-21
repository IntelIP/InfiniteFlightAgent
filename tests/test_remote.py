"""Remote MCP server over real HTTP (no model calls): token gate, health, tool listing."""

import asyncio
import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ifdispatcher import progress, remote

TOKEN = "test-internal-token"


@pytest.fixture(scope="module")
def server():
    # One server per process: the MCP session manager can only be started once.
    os.environ["IFD_INTERNAL_TOKEN"] = TOKEN
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(remote.create_app(), host="127.0.0.1", port=port, log_level="error")
    instance = uvicorn.Server(config)
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    for _ in range(100):
        if instance.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    instance.should_exit = True
    thread.join(timeout=5)


def test_health_is_open_and_mcp_requires_token(server):
    assert httpx.get(f"{server}/health").json()["status"] == "ok"
    assert httpx.post(f"{server}/mcp", json={}).status_code == 401
    wrong = httpx.post(f"{server}/mcp", json={}, headers={remote.TOKEN_HEADER: "nope"})
    assert wrong.status_code == 401


def test_mcp_client_lists_dispatcher_tools(server):
    async def list_tools():
        headers = {remote.TOKEN_HEADER: TOKEN}
        client = httpx.AsyncClient(headers=headers)
        async with streamable_http_client(f"{server}/mcp", http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return sorted(t.name for t in (await session.list_tools()).tools)

    assert asyncio.run(list_tools()) == [
        "approve_dispatch",
        "browser_status",
        "cancel_trip",
        "conversation_status",
        "list_saved_trips",
        "plan_flight",
        "trip_progress",
        "turn_status",
    ]


def test_long_turn_returns_running_then_result(monkeypatch):
    release = threading.Event()

    def slow_run(payload, thread_id, control=None, run_id=None):
        progress.set_status(thread_id, "running", run_id=run_id, trace={"run_id": run_id})
        release.wait(5)
        return {"status": "reply", "thread_id": thread_id, "reply": payload}

    monkeypatch.setattr(remote, "_run", slow_run)
    monkeypatch.setattr(remote, "WAIT_SECONDS", 0.05)

    async def scenario():
        first = await remote.plan_flight("hello", thread_id="t-long")
        busy = await remote.approve_dispatch("t-long", approve=True)
        still = await remote.turn_status("t-long")
        release.set()
        monkeypatch.setattr(remote, "WAIT_SECONDS", 5)
        return first, busy, still, await remote.turn_status("t-long")

    first, busy, still, done = asyncio.run(scenario())
    assert first["status"] == "running"
    assert busy["status"] == "busy" and busy["run_id"] == first["run_id"]
    assert still["status"] == "running"
    # A running turn already reports its root run id and trace.
    assert first["run_id"] and still["run_id"] == first["run_id"]
    assert still["trace"] == {"run_id": first["run_id"]}
    assert done["status"] == "reply"
    assert done["reply"]["messages"][0]["content"] == "hello"


def test_failed_turn_returns_its_trace_instead_of_an_error(monkeypatch):
    def failing_run(payload, thread_id, control=None, run_id=None):
        control.trace = {"run_id": run_id}
        progress.set_status(thread_id, "running", run_id=run_id, trace=control.trace)
        progress.finish_turn(thread_id, "failed", 0.0, error="RuntimeError")
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(remote, "_run", failing_run)

    async def scenario():
        return await remote.plan_flight("hello", thread_id="t-fail"), await remote.turn_status(
            "t-fail"
        )

    failed, again = asyncio.run(scenario())
    assert failed["status"] == "failed" and failed["error"] == "RuntimeError"
    assert failed["run_id"] and failed["trace"] == {"run_id": failed["run_id"]}
    assert again == failed  # turn_status reports the same failed turn, not an MCP error


def test_failed_and_cancelled_turns_refresh_their_trace_link(monkeypatch):
    from ifdispatcher import observability

    monkeypatch.setattr(remote, "paid_operations_enabled", lambda: True)
    from types import SimpleNamespace

    idle = SimpleNamespace(values={}, interrupts=())
    monkeypatch.setattr(remote, "_get_agent", lambda: SimpleNamespace(get_state=lambda c: idle))
    for thread, error in (("t-raise", RuntimeError("model down")), ("t-stop", None)):
        # The project lookup is in backoff at turn start and succeeds by the turn's end.
        links = iter([None, f"https://smith.example/r/{thread}"])
        monkeypatch.setattr(
            observability, "trace_link", lambda rid: {"run_id": rid, "url": next(links)}
        )

        def invoke(payload, thread_id, run_id, begin, error=error):
            begin()  # the root run started before the failure
            raise error or progress.TurnCancelled("owner")

        monkeypatch.setattr(remote, "_invoke", invoke)
        progress.start_turn(thread, "plan_flight")
        try:
            result = remote._run({"messages": []}, thread, run_id=thread)
        except RuntimeError:
            result = None
        final = {"run_id": thread, "url": f"https://smith.example/r/{thread}"}
        assert progress.read(thread)["trace"] == final
        if result:
            assert result["status"] == "cancelled" and result["trace"] == final


def test_turn_failing_before_its_root_run_publishes_no_trace_link(monkeypatch):
    from types import SimpleNamespace

    from ifdispatcher import observability

    monkeypatch.setattr(remote, "paid_operations_enabled", lambda: True)
    monkeypatch.setattr(observability, "trace_link", lambda rid: {"run_id": rid, "url": "dead"})
    idle = SimpleNamespace(values={}, interrupts=())
    monkeypatch.setattr(remote, "_get_agent", lambda: SimpleNamespace(get_state=lambda c: idle))
    for thread, error in (("t-early", RuntimeError("checkpoint down")), ("t-admit", None)):
        # Agent build, checkpoint read or browser admission fails before agent.invoke.
        def invoke(payload, thread_id, run_id, begin, error=error):
            raise error or progress.TurnCancelled("owner")

        monkeypatch.setattr(remote, "_invoke", invoke)
        progress.start_turn(thread, "plan_flight")
        try:
            result = remote._run({"messages": []}, thread, run_id=thread)
        except RuntimeError:
            result = None
        record = progress.read(thread)
        assert record["run_id"] == thread and record["trace"] is None
        if result:
            assert result["status"] == "cancelled" and result["trace"] is None


def test_failed_response_keeps_the_failed_turns_identity(monkeypatch):
    from concurrent.futures import Future

    failed = Future()
    failed.set_exception(RuntimeError("model down"))
    control = progress.TurnControl("t-race", 60)
    control.run_id, control.trace = "r-old", {"run_id": "r-old", "url": None}
    monkeypatch.setitem(remote._turns, "t-race", failed)
    monkeypatch.setitem(remote._controls, "t-race", control)
    # A newer turn on the thread replaced the durable record before the failure was reported.
    progress.start_turn("t-race", "plan_flight")
    result = asyncio.run(remote._wait("t-race"))
    assert result["status"] == "failed"
    assert result["run_id"] == "r-old" and result["trace"] == control.trace


def test_turn_status_recovery_paths_carry_top_level_trace(monkeypatch):
    from concurrent.futures import Future

    trace = {"run_id": "r-restored", "url": "https://smith.example/r/r-restored"}
    progress.start_turn("t-restored", "plan_flight")
    progress.finish_turn("t-restored", "failed", 0.0, run_id="r-restored", trace=trace)
    restored = asyncio.run(remote.turn_status("t-restored"))  # after a restart
    assert restored["status"] == "failed"
    assert restored["run_id"] == "r-restored" and restored["trace"] == trace

    done = Future()
    done.set_result({"status": "approval_required", "thread_id": "t-withdrawn"})
    monkeypatch.setitem(remote._turns, "t-withdrawn", done)
    progress.start_turn("t-withdrawn", "plan_flight")
    progress.finish_turn("t-withdrawn", "cancelled", 0.0, run_id="r-cancel", trace=trace)
    cancelled = asyncio.run(remote.turn_status("t-withdrawn"))  # cancel_trip after completion
    assert cancelled["status"] == "cancelled"
    assert cancelled["run_id"] == "r-cancel" and cancelled["trace"] == trace


def test_turn_status_for_unknown_thread():
    result = asyncio.run(remote.turn_status("t-never-started"))
    assert result["status"] == "not_found"


def test_mcp_http_dispatch_approval_saved_trip_and_metrics(server, tmp_path, monkeypatch):
    """Exercise the actual HTTP tools, graph and Store with controlled provider responses."""
    import json
    from datetime import datetime, timezone

    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from ifdispatcher import agent, observability, operations, workflow
    from ifdispatcher.core import Store
    from test_agent_workflow import ScriptedModel, neo_plan

    monkeypatch.setenv("IFD_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(workflow, "_store", lambda: Store(tmp_path))
    monkeypatch.setattr(operations, "open_store", lambda: Store(tmp_path))
    monkeypatch.setattr(agent.flights, "airport_name", lambda code: "Test airport")
    monkeypatch.setattr(agent.flights, "airport_elevation", lambda code: 312)
    monkeypatch.setattr(agent.flights, "local_time", lambda value, code: value)
    monkeypatch.setattr(workflow.artifacts, "upload", lambda *a, **k: [])
    raw = neo_plan(datetime.now(timezone.utc).isoformat(), "2026-11-08T12:00:00Z")
    monkeypatch.setattr(workflow, "fetch_sync", lambda *a, **k: raw)
    feedback = []
    monkeypatch.setattr(
        observability, "write_feedback", lambda rid, signals: feedback.append((rid, signals))
    )
    link = lambda rid: {"run_id": rid, "url": f"https://smith.example/r/{rid}"}  # noqa: E731
    monkeypatch.setattr(observability, "trace_link", link)

    def generation(fields, click, _screenshots, before_click):
        before_click()
        observability.browser_opened("controlled-mcp-session")
        observability.browser_closed("controlled-mcp-session")
        return {"status": "generated", "session": "controlled-provider"}

    monkeypatch.setattr(workflow.simbrief_browser, "generate", generation)
    leg = {
        "trip": "mcp-http-trip",
        "leg": "1",
        "origin": "KIAD",
        "destination": "KEWR",
        "sim_aircraft": "A21N",
        "departure_local_date": "2026-11-08",
        "departure_utc": "2026-11-08T12:00:00Z",
        "private_callsign": "N320HD",
    }
    model = ScriptedModel(
        [
            AIMessage("", tool_calls=[{"id": "dispatch", "name": "dispatch_flight", "args": leg}]),
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "generate",
                        "name": "generate_in_simbrief",
                        "args": {"trip": leg["trip"], "leg": "1"},
                    }
                ],
            ),
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "finalize",
                        "name": "finalize_dispatch",
                        "args": {"trip": leg["trip"], "leg": "1"},
                    }
                ],
            ),
            AIMessage("The saved briefing is ready."),
        ]
    )
    graph = agent.build_agent(model=model, checkpointer=InMemorySaver())
    monkeypatch.setattr(remote, "_get_agent", lambda: graph)

    async def journey():
        client = httpx.AsyncClient(headers={remote.TOKEN_HEADER: TOKEN})
        async with streamable_http_client(f"{server}/mcp", http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(name, args):
                    result = await session.call_tool(name, args)
                    assert not result.isError
                    return result.structuredContent or json.loads(result.content[0].text)

                thread = "mcp-http-approval"
                asked = await call(
                    "plan_flight", {"message": "Prepare the private flight.", "thread_id": thread}
                )
                assert asked["status"] == "approval_required"
                assert Store(tmp_path).trips() == []  # no preparation/generation before approval
                assert asked["workflow"]["outcome"] == "approval_required"
                assert asked["trace"] == link(asked["run_id"])  # approval prompt links its trace
                done = await call("approve_dispatch", {"thread_id": thread, "approve": True})
                while done["status"] == "running":
                    done = await call("turn_status", {"thread_id": thread})
                assert done["status"] == "reply"
                assert done["workflow"]["outcome"] == "briefing_ready"
                assert done["trace"] == link(done["run_id"])
                progress_view = await call("trip_progress", {"thread_id": thread})
                assert progress_view["turn"]["trace"] == link(done["run_id"])
                assert done["provider_usage"][0]["released"] is True
                assert "elapsed_s" in done["provider_usage"][0]
                saved = await call("list_saved_trips", {"trip": leg["trip"]})
                assert saved["legs"][0]["snapshot_sha256"]
                assert saved["legs"][0]["briefing_markdown"].startswith("**SPAWN:**")
                remote._turns.pop(
                    thread
                )  # an in-memory turn lost on restart does not lose the checkpoint
                restored = await call("conversation_status", {"thread_id": thread})
                assert restored["reply"] == "The saved briefing is ready."
                return asked, done

    asked, done = asyncio.run(journey())
    assert [rid for rid, _ in feedback] == [asked["run_id"], done["run_id"]]
    assert [s["outcome"] for _, s in feedback] == ["approval_required", "briefing_ready"]


def test_trace_link_builds_one_click_url_and_degrades_to_run_id(monkeypatch):
    from types import SimpleNamespace

    import langsmith

    from ifdispatcher import observability

    monkeypatch.setattr(observability, "_trace_home", {})
    monkeypatch.setattr(observability, "_tracing_key", lambda: None)
    assert observability.trace_link("r1") is None  # tracing off: nothing to link

    monkeypatch.setattr(observability, "_tracing_key", lambda: "lsv2_synthetic")
    monkeypatch.setenv("LANGSMITH_PROJECT", "infinite-flight-dispatcher")
    reads = []

    class Client:
        api_url = "https://api.smith.langchain.com"

        def __init__(self, **_):
            pass

        def read_project(self, project_name):
            reads.append(project_name)
            if len(reads) == 1:
                raise ConnectionError("offline")
            return SimpleNamespace(tenant_id="ws", id="proj")

    monkeypatch.setattr(langsmith, "Client", Client)
    assert observability.trace_link("r1") == {"run_id": "r1", "url": None}
    assert observability.trace_link("r1b") == {"run_id": "r1b", "url": None}
    assert len(reads) == 1  # a failed lookup backs off instead of repeating on every turn
    observability._trace_home["retry_at"] = 0.0  # the backoff has elapsed
    url = "https://smith.langchain.com/o/ws/projects/p/proj/r/r2?trace_id=r2"
    assert observability.trace_link("r2") == {"run_id": "r2", "url": url}
    observability.trace_link("r3")
    assert reads == ["infinite-flight-dispatcher"] * 2  # looked up once after success
    assert observability.run_metadata("remote")["product"] == "jumpseat"


def test_concurrent_turns_never_wait_on_the_same_project_lookup(monkeypatch):
    from ifdispatcher import observability

    monkeypatch.setattr(observability, "_trace_home", {})
    monkeypatch.setattr(observability, "_tracing_key", lambda: "lsv2_synthetic")
    entered, release, lookups = threading.Event(), threading.Event(), []

    def slow_lookup(key):  # a LangSmith call hanging on a network timeout
        lookups.append(key)
        entered.set()
        release.wait(5)
        observability._trace_home["retry_at"] = time.monotonic() + 300

    monkeypatch.setattr(observability, "_look_up_trace_home", slow_lookup)
    first = threading.Thread(target=observability.trace_link, args=("r1",))
    first.start()
    assert entered.wait(5)
    # While one worker retries, the others return the run id at once instead of waiting.
    assert observability.trace_link("r2") == {"run_id": "r2", "url": None}
    release.set()
    first.join(5)
    assert len(lookups) == 1


def test_kill_switch_turn_publishes_no_trace_link(monkeypatch):
    from ifdispatcher import observability

    monkeypatch.setattr(remote, "paid_operations_enabled", lambda: False)
    monkeypatch.setattr(observability, "trace_link", lambda rid: {"run_id": rid, "url": "dead"})
    progress.start_turn("t-off", "plan_flight")
    result = remote._run({"messages": []}, "t-off", run_id="r-off")
    assert result["status"] == "paid_operations_disabled"
    assert result["run_id"] == "r-off" and result["trace"] is None  # same schema, no dead link
    turn = progress.turn_view(progress.read("t-off"), live=False)
    assert turn["trace"] is None and turn["run_id"] == "r-off"


def test_completion_trace_link_replaces_the_start_time_link(monkeypatch):
    from ifdispatcher import observability

    monkeypatch.setattr(remote, "paid_operations_enabled", lambda: True)
    # The project lookup is in backoff at turn start, then succeeds before the turn ends.
    monkeypatch.setattr(observability, "trace_link", lambda rid: {"run_id": rid, "url": None})
    final = {"run_id": "r-late", "url": "https://smith.example/r/r-late"}

    def invoke(payload, thread_id, run_id, begin):
        return {"status": "reply", "thread_id": thread_id, "run_id": run_id, "trace": final}

    monkeypatch.setattr(remote, "_invoke", invoke)
    progress.start_turn("t-late", "plan_flight")
    remote._run({"messages": []}, "t-late", run_id="r-late")
    assert progress.turn_view(progress.read("t-late"), live=False)["trace"] == final
