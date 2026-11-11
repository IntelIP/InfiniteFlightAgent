"""A slow controlled turn must survive HTTP's default read timeout and long-polling."""

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_mcp_replay_keeps_a_slow_turn_and_polls_to_completion():
    # Contain the old lost-SSE hang in a subprocess. Scale the ordinary 5s HTTP read
    # timeout down to 10ms; the operation spans several server long-poll intervals.
    script = r"""
import json, time
from types import SimpleNamespace
import httpx._config
from langchain_core.messages import AIMessage
from ifdispatcher import remote, observability
from mcp_replay import MCPServer, MCPDriver

httpx._config.DEFAULT_TIMEOUT_CONFIG.read = 0.01
remote.WAIT_SECONDS = 0.05
remote.paid_operations_enabled = lambda: True
observability.write_feedback = lambda *a, **k: None

class SlowGraph:
    def __init__(self):
        self.state = {"messages": []}
        self.calls = 0
    def get_state(self, config):
        return SimpleNamespace(values=self.state)
    def invoke(self, payload, config, **kwargs):
        self.calls += 1
        time.sleep(0.16)
        self.state = {"messages": [AIMessage("Controlled slow reply")]}
        return SimpleNamespace(value=self.state, interrupts=[])

with MCPServer() as server:
    graph = SlowGraph()
    driver = MCPDriver(server.url, graph, None, {})
    remote._get_agent = lambda: driver
    reply = driver.call("plan_flight", {"message": "controlled", "thread_id": "slow-replay"})
    assert reply["status"] == "reply", reply
    assert reply["reply"] == "Controlled slow reply"
    assert graph.calls == 1
    assert remote._turns["slow-replay"].done()
print("MCP_SLOW_TURN_PASSED")
"""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "evals")])}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MCP_SLOW_TURN_PASSED" in result.stdout
