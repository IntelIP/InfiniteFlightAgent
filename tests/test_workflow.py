import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ifdispatcher.core import Dispatch, Store, fetch, normalize

FIXTURE = Path("docs/research/evidence/simbrief-b38m-parser-fixture.json")


def request(leg="out", revision=1):
    return Dispatch(
        trip="case",
        leg=leg,
        revision=revision,
        origin="KIAD",
        destination="KEWR",
        aircraft="B38M",
        departure="2026-10-29T01:00:00Z",
        units="KGS",
        passengers=0,
    )


def test_nested_data_and_zero():
    raw = json.loads(FIXTURE.read_text())
    raw["tlr"]["takeoff"]["runway"].reverse()
    selected = next(r for r in raw["tlr"]["takeoff"]["runway"] if r["identifier"] == "30")
    selected["distance_margin"] = 0
    result = normalize(json.dumps(raw).encode())
    assert result["selected_takeoff"]["identifier"] == "30"
    assert result["selected_takeoff"]["distance_margin"] == 0
    assert result["target_status"] == "unavailable"
    assert result["tlr"] == raw["tlr"]


def test_persistence_and_immutable_revisions(tmp_path):
    s = Store(tmp_path)
    raw = FIXTURE.read_bytes()
    for leg in ["out", "return"]:
        s.prepare(request(leg))
        s.save("case", leg, 1, raw, None)
    changed = json.loads(raw)
    changed["params"]["time_generated"] = "2026-10-30T00:00:00Z"
    with pytest.raises(ValueError, match="revision_conflict"):
        s.save("case", "out", 1, json.dumps(changed).encode(), None)
    s.prepare(request(revision=2))
    s.save("case", "out", 2, json.dumps(changed).encode(), None)
    reopened = Store(tmp_path)
    assert (
        reopened.read("case", "return", 1)["data"]["generated_at"]
        != changed["params"]["time_generated"]
    )
    assert (
        reopened.read("case", "out", 1)["raw_sha256"]
        == reopened.read("case", "return", 1)["raw_sha256"]
    )
    with reopened.connect() as db:
        assert (
            db.execute("SELECT raw FROM snapshots WHERE leg=? AND revision=1", ("out",)).fetchone()[
                0
            ]
            == raw
        )


def test_preparation_and_mismatch(tmp_path):
    s = Store(tmp_path)
    partial = Dispatch(trip="case", leg="out", revision=1)
    assert s.prepare(partial)["status"] == "missing_input"
    s.prepare(request())
    with pytest.raises(ValueError, match="revision_conflict"):
        s.prepare(request().model_copy(update={"passengers": 1}))
    raw = json.loads(FIXTURE.read_text())
    raw["destination"]["icao_code"] = "KJFK"
    with pytest.raises(ValueError, match="identity_mismatch"):
        s.save("case", "out", 1, json.dumps(raw).encode(), None)
    with pytest.raises(ValueError, match="missing_snapshot"):
        s.read("case", "out", 1)
    with pytest.raises(ValueError):
        Dispatch(**{**request().model_dump(), "unknown": True})
    with pytest.raises(ValueError):
        Dispatch(**{**request().model_dump(), "departure": "2026-10-29T01:00:00"})


def test_provider_failure_and_single_request():
    calls = []

    def handler(req):
        calls.append(req)
        assert req.url.params["json"] == "v2"
        assert req.url.params["client"]
        return httpx.Response(503)

    with pytest.raises(ValueError, match="http_error: 503"):
        asyncio.run(fetch("fixture-user", transport=httpx.MockTransport(handler)))
    assert len(calls) == 1
    for raw in [b"[]", b"not-json", b'{"fetch":{"status":"Error"}}']:
        with pytest.raises(ValueError):
            normalize(raw)


def test_stdio_protocol(tmp_path):
    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "ifdispatcher.server"],
            env={
                **os.environ,
                "PYTHONPATH": str(Path("src").resolve()),
                "IFD_DATA_DIR": str(tmp_path),
            },
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                assert "retrieve_simbrief_plan" in names
                assert "submit_dispatch" not in names
                result = await session.call_tool(
                    "prepare_simbrief_dispatch", {"request": request().model_dump(mode="json")}
                )
                assert not result.isError
                assert result.structuredContent["status"] == "prepared"
                result = await session.call_tool(
                    "retrieve_simbrief_plan",
                    {"trip": "case", "leg": "out", "revision": 1, "user_requested": False},
                )
                assert result.isError
                result = await session.call_tool("simbrief_capabilities", {})
                assert result.structuredContent["generation"] is False

    asyncio.run(run())
