"""Remote MCP server for the deployed dispatcher (Streamable HTTP on :8080).

Runs in the Cloudflare Container behind the Worker. Cloudflare Access authenticates the user;
the Worker adds X-IFD-Internal-Token, which this server requires on every request except
/health. Conversations persist per thread_id in the checkpointer (Neon in deployment).

Agent turns run in a background thread so a long turn (SimBrief generation takes about two
minutes) does not hold the MCP call open past client timeouts: a tool waits up to
WAIT_SECONDS, then returns status "running" and the client polls turn_status.
"""

import asyncio
import hmac
import os
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from langgraph.types import Command
from starlette.requests import Request
from starlette.responses import JSONResponse

from ifdispatcher.config import export_tracing_settings, paid_operations_enabled, setting

TOKEN_HEADER = "x-ifd-internal-token"
WAIT_SECONDS = 25
_agent = None
_turns: dict[str, Future] = {}  # latest turn per thread_id
_pool = ThreadPoolExecutor(max_workers=4)


def _get_agent():
    global _agent
    if _agent is None:
        from ifdispatcher.agent import build_agent, checkpointer

        _agent = build_agent(checkpointer=checkpointer())
    return _agent


mcp = FastMCP(
    "InfiniteFlightDispatcher",
    stateless_http=True,
    # Host checks are replaced by the internal token: only the Worker can reach this server.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _turn(result, thread_id: str) -> dict[str, Any]:
    if result.interrupts:
        request = result.interrupts[0].value["action_requests"][0]
        return {
            "status": "approval_required",
            "thread_id": thread_id,
            "action": request["name"],
            "inputs": request["args"],
            "summary": request["description"],
            "next": "Show the summary to the user, then call approve_dispatch with their answer.",
        }
    return {"status": "reply", "thread_id": thread_id, "reply": result.value["messages"][-1].text}


def _run(payload, thread_id: str) -> dict[str, Any]:
    if not paid_operations_enabled():
        return {"status": "paid_operations_disabled", "thread_id": thread_id}
    config = {"configurable": {"thread_id": thread_id}, "tags": ["remote"]}
    return _turn(_get_agent().invoke(payload, config=config, version="v2"), thread_id)


async def _wait(thread_id: str) -> dict[str, Any]:
    turn = _turns[thread_id]
    try:
        # shield: a timeout must not cancel the turn itself.
        return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(turn)), WAIT_SECONDS)
    except TimeoutError:
        return {
            "status": "running",
            "thread_id": thread_id,
            "next": "Still working. Call turn_status with this thread_id in about 20 seconds.",
        }


async def _start(payload, thread_id: str) -> dict[str, Any]:
    running = _turns.get(thread_id)
    if running and not running.done():
        return {
            "status": "busy",
            "thread_id": thread_id,
            "next": "A turn is still running on this thread. Call turn_status instead.",
        }
    _turns[thread_id] = _pool.submit(_run, payload, thread_id)
    return await _wait(thread_id)


@mcp.tool()
async def plan_flight(message: str, thread_id: str | None = None) -> dict[str, Any]:
    """Send the user's message to the Infinite Flight dispatcher and return its reply.

    Start a conversation without thread_id; pass the returned thread_id on every later message
    of the same trip. Relay the reply to the user as written. If the status is
    approval_required, show the summary and ask the user before calling approve_dispatch. If the
    status is running, call turn_status with the thread_id until it returns the reply.
    """
    thread_id = thread_id or f"trip-{uuid.uuid4().hex[:10]}"
    payload = {"messages": [{"role": "user", "content": message}]}
    return await _start(payload, thread_id)


@mcp.tool()
async def approve_dispatch(
    thread_id: str, approve: bool, note: str | None = None
) -> dict[str, Any]:
    """Answer a pending approval for thread_id. approve=true prepares and generates the SimBrief
    plan (about two minutes, so this usually returns status running; poll turn_status) and
    then returns the briefing; approve=false declines with the user's note. Only call after the
    user explicitly answered.
    """
    decision = {"type": "approve"} if approve else {"type": "reject", "message": note or "declined"}
    payload = Command(resume={"decisions": [decision]})
    return await _start(payload, thread_id)


@mcp.tool()
async def turn_status(thread_id: str) -> dict[str, Any]:
    """Result of the latest plan_flight or approve_dispatch call on thread_id after it returned
    status running. Returns running again (call later), or the reply / approval request.
    """
    if thread_id not in _turns:
        return {
            "status": "not_found",
            "thread_id": thread_id,
            "next": "No turn on this thread since the server started. If one was running, the "
            "server restarted; send plan_flight on this thread to ask where it stands.",
        }
    return await _wait(thread_id)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "paid_operations_enabled": paid_operations_enabled(),
            "database": bool(setting("DATABASE_URL")),
        }
    )


def create_app():
    app = mcp.streamable_http_app()
    expected = setting("IFD_INTERNAL_TOKEN") or ""

    async def gate(scope, receive, send):
        if scope["type"] == "http" and scope["path"] != "/health":
            headers = dict(scope.get("headers") or [])
            given = headers.get(TOKEN_HEADER.encode(), b"").decode()
            if not expected or not hmac.compare_digest(given, expected):
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await app(scope, receive, send)

    return gate


def main() -> None:
    import uvicorn

    export_tracing_settings()
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
