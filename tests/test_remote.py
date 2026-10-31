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

    assert asyncio.run(list_tools()) == ["approve_dispatch", "plan_flight"]
