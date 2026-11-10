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

from ifdispatcher import remote

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
        "conversation_status",
        "list_saved_trips",
        "plan_flight",
        "turn_status",
    ]


def test_long_turn_returns_running_then_result(monkeypatch):
    release = threading.Event()

    def slow_run(payload, thread_id):
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
    assert busy["status"] == "busy"
    assert still["status"] == "running"
    assert done["status"] == "reply"
    assert done["reply"]["messages"][0]["content"] == "hello"


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
                done = await call("approve_dispatch", {"thread_id": thread, "approve": True})
                while done["status"] == "running":
                    done = await call("turn_status", {"thread_id": thread})
                assert done["status"] == "reply"
                assert done["workflow"]["outcome"] == "briefing_ready"
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
