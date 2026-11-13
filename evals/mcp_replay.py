"""Loopback-only MCP transport for controlled workflow replay, using the production app."""

import asyncio
import os
import json
import socket
import threading
import time
from datetime import timedelta
from types import SimpleNamespace

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from langgraph.types import Command
from langsmith import tracing_context

from ifdispatcher import remote

TOKEN = "controlled-workflow-replay-token"


class MCPServer:
    def __enter__(self):
        self.old_token = os.environ.get("IFD_INTERNAL_TOKEN")
        os.environ["IFD_INTERNAL_TOKEN"] = TOKEN
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}/mcp"
        self.server = uvicorn.Server(
            uvicorn.Config(remote.create_app(), host="127.0.0.1", port=port, log_level="error")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 5
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("controlled MCP server failed to start")
            time.sleep(0.01)
        return self

    def __exit__(self, *_):
        self.server.should_exit = True
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError("controlled MCP server failed to stop")
        if self.old_token is None:
            os.environ.pop("IFD_INTERNAL_TOKEN", None)
        else:
            os.environ["IFD_INTERNAL_TOKEN"] = self.old_token


class MCPDriver:
    def __init__(self, url, graph, measurement, run):
        self.url, self.graph, self.measurement, self.run = url, graph, measurement, run

    def get_state(self, config):
        return self.graph.get_state(config)

    def invoke(self, payload, config, **kwargs):
        # remote._run invokes this proxy from its worker thread; disable ambient tracing
        # there too and attach the same stage measurements as direct graph replay.
        if threading.current_thread() is not threading.main_thread():
            with tracing_context(enabled=False):
                return self.graph.invoke(
                    payload, {**config, "callbacks": [self.measurement]}, **kwargs
                )
        thread = config["configurable"]["thread_id"]
        if isinstance(payload, Command):
            decisions = payload.resume["decisions"]
            if len(decisions) != 1:
                raise ValueError(
                    "MCP replay requires the production single-action approval contract"
                )
            name, args = (
                "approve_dispatch",
                {
                    "thread_id": thread,
                    "approve": decisions[0]["type"] == "approve",
                },
            )
        else:
            name, args = (
                "plan_flight",
                {
                    "thread_id": thread,
                    "message": payload["messages"][-1]["content"],
                },
            )
        result = self.call(name, args)
        self.run.setdefault("mcp_responses", []).append(result)
        state = self.graph.get_state(config).values
        interrupts = []
        if result["status"] == "approval_required":
            interrupts = [
                SimpleNamespace(
                    value={
                        "action_requests": [
                            {
                                "name": result["action"],
                                "args": result["inputs"],
                                "description": result["summary"],
                            }
                        ]
                    }
                )
            ]
        elif result["status"] == "cancelled":
            # A cancelled or expired turn ends without a model reply; the harness inspects
            # durable progress next instead of treating it as a transport failure.
            self.run["cancelled"] = True
            self.run.setdefault("mcp_outputs", []).append({"tool": name, "output": result})
        elif result["status"] != "reply":
            raise RuntimeError(f"unexpected MCP outcome: {result['status']}")
        return SimpleNamespace(value=state, interrupts=interrupts)

    def call(self, name, args):
        async def request():
            # A supplied HTTP client bypasses the SDK's long SSE-read defaults. Keep
            # it above the server's long-poll interval and also bound a lost RPC reply.
            rpc_seconds = remote.WAIT_SECONDS + 10
            async with httpx.AsyncClient(
                headers={remote.TOKEN_HEADER: TOKEN},
                timeout=httpx.Timeout(rpc_seconds, connect=5),
            ) as client:
                async with streamable_http_client(self.url, http_client=client) as (read, write, _):
                    async with ClientSession(
                        read, write, read_timeout_seconds=timedelta(seconds=rpc_seconds)
                    ) as session:
                        await session.initialize()
                        result = await session.call_tool(name, args)

                        def output(result):
                            return result.structuredContent or json.loads(result.content[0].text)

                        deadline = time.monotonic() + 240
                        while not result.isError and output(result).get("status") == "running":
                            if time.monotonic() > deadline:
                                raise TimeoutError("controlled MCP turn deadline exceeded")
                            await asyncio.sleep(0.02)
                            result = await session.call_tool(
                                "turn_status", {"thread_id": args["thread_id"]}
                            )
                        if result.isError:
                            raise RuntimeError(str(result.content))
                        return output(result)

        return asyncio.run(request())
