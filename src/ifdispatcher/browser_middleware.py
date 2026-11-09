"""Agent integration for the browser guard also enforced at the direct-call boundary."""

import json

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from ifdispatcher import simbrief_browser
from ifdispatcher.browser_budget import BrowserLimit

BROWSER_TOOLS = {"simbrief_airframes", "generate_in_simbrief", "finalize_dispatch"}


class BrowserBudgetMiddleware(AgentMiddleware):
    """Use the invocation's shared session, or a short scope for standalone graph calls."""

    @staticmethod
    def _error(request, exc):
        return ToolMessage(
            json.dumps({"status": "browser_limited", "reason": str(exc), "retryable": False}),
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
            status="error",
        )

    def wrap_tool_call(self, request, handler):
        if request.tool_call["name"] not in BROWSER_TOOLS:
            return handler(request)
        try:
            with simbrief_browser.session_scope():
                return handler(request)
        except BrowserLimit as exc:
            return self._error(request, exc)

    async def awrap_tool_call(self, request, handler):
        if request.tool_call["name"] not in BROWSER_TOOLS:
            return await handler(request)
        try:
            with simbrief_browser.session_scope():
                return await handler(request)
        except BrowserLimit as exc:
            return self._error(request, exc)
