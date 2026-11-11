"""Revision approval journeys through the real graph and MCP tools; providers are controlled."""

import asyncio
import json
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ifdispatcher import agent, observability, operations, remote, workflow
from ifdispatcher.core import open_store
from test_agent_workflow import ScriptedModel, neo_plan


@pytest.fixture
def saved_leg(tmp_path, monkeypatch):
    monkeypatch.setenv("IFD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    provider_calls = []

    def airport(path, params=None):
        provider_calls.append(path)
        assert path.startswith("/airports/")
        return {"name": "Controlled airport", "timezone": "UTC", "elevation": 312}

    def unexpected(*args, **kwargs):
        pytest.fail("revision preparation must not generate, retrieve or upload a plan")

    monkeypatch.setattr(workflow.flights, "_get", airport)
    monkeypatch.setattr(workflow.simbrief_browser, "generate", unexpected)
    monkeypatch.setattr(workflow, "fetch_sync", unexpected)
    monkeypatch.setattr(workflow.artifacts, "upload", unexpected)
    assert (
        workflow.dispatch_flight(
            "T",
            "1",
            "KIAD",
            "KEWR",
            "A21N",
            "2026-11-08",
            departure_utc="2026-11-08T12:00:00Z",
            private_callsign="N320HD",
            passengers=15,
            route="DCT",
        )["status"]
        == "awaiting_simbrief_generation"
    )
    store = open_store()
    raw = json.loads(neo_plan(datetime.now(timezone.utc).isoformat(), "2026-11-08T12:00:00Z"))
    raw["general"] = {"route": "DCT"}
    store.save(
        "T",
        "1",
        1,
        json.dumps(raw).encode(),
        None,
    )
    meta = store.read_meta("T", "1", 1)
    store.save_meta("T", "1", 1, {**meta, "briefing": "Retained original briefing"})
    return store, provider_calls


def revision_call(**extra):
    return {
        "name": "revise_dispatch",
        "id": "revision",
        "args": {
            "trip": "T",
            "leg": "1",
            "base_revision": 1,
            "changes": {"passengers": 12, "route": "DCT NEW"},
            **extra,
        },
    }


def retained(store):
    return (
        store.revisions("T", "1"),
        store.read_meta("T", "1", 1),
        store.read("T", "1", 1),
        store.read_raw("T", "1", 1),
    )


@pytest.mark.parametrize(
    "extra, reason",
    [
        ({"changes": {"alternate": "KOAK", "cruise_altitude": 35000}}, "unsupported_changes"),
        ({"leg": "missing"}, "missing_dispatch"),
        ({"base_revision": 0}, "revision_conflict"),
        ({"changes": {"departure_utc": "Friday"}}, "invalid_departure"),
        ({"changes": {"departure_utc": "2026-11-08T13:00:00"}}, "invalid_departure"),
        ({"changes": {"departure_utc": None}}, "invalid_departure"),
        ({"changes": {"departure_utc": 123}}, "invalid_departure"),
        ({"changes": None}, "validation error"),
    ],
)
def test_invalid_revision_recovers_before_approval_or_provider(saved_leg, extra, reason):
    store, provider_calls = saved_leg
    before = retained(store)
    graph = agent.build_agent(
        model=ScriptedModel(
            [
                AIMessage("", tool_calls=[revision_call(**extra)]),
                AIMessage("Please correct the revision."),
            ]
        ),
        checkpointer=InMemorySaver(),
    )
    result = graph.invoke(
        {"messages": [{"role": "user", "content": "Revise this leg"}]},
        {"configurable": {"thread_id": "invalid-revision"}},
        version="v2",
    )
    assert not result.interrupts
    refused = [m for m in result.value["messages"] if m.type == "tool"]
    assert len(refused) == 1 and refused[0].status == "error"
    refusal = json.loads(refused[0].content)
    assert refusal["status"] == "refused" and reason in refusal["reason"]
    if reason == "unsupported_changes":
        assert all(field in refusal["reason"] for field in ("alternate", "cruise_altitude"))
        assert "Supported revision fields:" in refusal["reason"]
    assert result.value["messages"][-1].text == "Please correct the revision."
    assert provider_calls == []
    assert retained(store) == before


def test_revised_departure_with_broken_connection_is_refused_without_provider(saved_leg):
    store, provider_calls = saved_leg
    workflow.dispatch_flight(
        "T",
        "0",
        "KJFK",
        "KIAD",
        "A21N",
        "2026-11-08",
        departure_utc="2026-11-08T09:00:00Z",
        private_callsign="N320HD",
    )
    meta = store.read_meta("T", "0", 1)
    store.save_meta("T", "0", 1, {**meta, "planned_arrival": "2026-11-08T11:45:00Z"})
    before = retained(store)
    result = agent.revise_dispatch.invoke(
        {
            **revision_call()["args"],
            "changes": {"departure_utc": "2026-11-08T12:15:00Z"},
        }
    )
    assert result["status"] == "error" and "connection_conflict" in result["error"]
    assert "0 h 30 min" in result["error"]
    assert provider_calls == [] and retained(store) == before


@pytest.mark.parametrize("approve", [False, True])
def test_mcp_recovers_then_requires_consent_for_exact_supported_revision(
    saved_leg,
    monkeypatch,
    approve,
):
    store, provider_calls = saved_leg
    before = retained(store)
    supported = revision_call()
    graph = agent.build_agent(
        model=ScriptedModel(
            [
                AIMessage(
                    "",
                    tool_calls=[
                        revision_call(changes={"alternate": "KOAK", "cruise_altitude": 35000})
                    ],
                ),
                AIMessage("Alternate and cruise altitude revisions are not supported."),
                AIMessage("", tool_calls=[supported]),
                AIMessage("Revision decision received."),
            ]
        ),
        checkpointer=InMemorySaver(),
    )
    monkeypatch.setattr(remote, "_get_agent", lambda: graph)
    monkeypatch.setattr(remote, "paid_operations_enabled", lambda: True)
    monkeypatch.setattr(observability, "write_feedback", lambda *args: None)
    thread = f"revision-mcp-{approve}"

    async def call(name, args):
        result = await remote.mcp.call_tool(name, args)
        return result[1] if isinstance(result, tuple) else json.loads(result[0].text)

    async def journey():
        refused = await call(
            "plan_flight", {"message": "Change altitude and alternate", "thread_id": thread}
        )
        assert refused["status"] == "reply"
        assert "not supported" in refused["reply"]
        assert refused["provider_usage"] == [] and provider_calls == []
        assert retained(store) == before
        asked = await call(
            "plan_flight", {"message": "Change load and route instead", "thread_id": thread}
        )
        assert asked["status"] == "approval_required" and asked["action"] == "revise_dispatch"
        assert asked["inputs"] == supported["args"]
        assert "12 passengers" in asked["summary"] and "DCT NEW" in asked["summary"]
        assert "2026-11-08T12:00:00" in asked["summary"] and "A21N" in asked["summary"]
        assert retained(store) == before
        done = await call("approve_dispatch", {"thread_id": thread, "approve": approve})
        assert done["status"] == "reply"
        return done

    try:
        asyncio.run(journey())
    finally:
        remote._turns.pop(thread, None)
    assert retained(store)[1:] == before[1:]
    revisions = store.revisions("T", "1")
    assert len(revisions) == (2 if approve else 1)
    if approve:
        assert revisions[-1]["revision"] == 2
        assert revisions[-1]["passengers"] == 12 and revisions[-1]["route"] == "DCT NEW"
        assert store.read_request("T", "1", 3) is None
        calls_before = list(provider_calls)
        repeated = agent.revise_dispatch.invoke(supported["args"])
        assert repeated["status"] == "error" and "revision_conflict" in repeated["error"]
        assert provider_calls == calls_before and len(store.revisions("T", "1")) == 2


def test_approval_edit_cannot_sneak_in_unsupported_revision(saved_leg):
    store, provider_calls = saved_leg
    before = retained(store)
    graph = agent.build_agent(
        model=ScriptedModel(
            [AIMessage("", tool_calls=[revision_call()]), AIMessage("Edit refused.")]
        ),
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "edited-revision"}}
    assert graph.invoke(
        {"messages": [{"role": "user", "content": "Revise route"}]},
        config,
        version="v2",
    ).interrupts
    provider_calls.clear()
    result = graph.invoke(
        Command(
            resume={
                "decisions": [
                    {
                        "type": "edit",
                        "edited_action": {
                            "name": "revise_dispatch",
                            "args": revision_call(changes={"cruise_altitude": 35000})["args"],
                        },
                    }
                ]
            }
        ),
        config,
        version="v2",
    )
    tool_result = next(m for m in result.value["messages"] if m.type == "tool")
    assert "unsupported_changes" in tool_result.content
    # The resumed approval description may reread airport metadata; the edited tool itself
    # must preserve all prior data and reject rather than silently dropping the change.
    assert retained(store) == before


def test_saved_base_changed_while_awaiting_approval_is_recoverable(saved_leg):
    store, provider_calls = saved_leg
    graph = agent.build_agent(
        model=ScriptedModel(
            [AIMessage("", tool_calls=[revision_call()]), AIMessage("Inspect the latest revision.")]
        ),
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "stale-approval"}}
    assert graph.invoke(
        {"messages": [{"role": "user", "content": "Revise route"}]},
        config,
        version="v2",
    ).interrupts
    operations.revise("T", "1", {"passengers": 9}, 1)
    before = retained(store)
    provider_calls.clear()
    result = graph.invoke(
        Command(resume={"decisions": [{"type": "approve"}]}), config, version="v2"
    )
    assert not result.interrupts
    assert (
        "revision_conflict" in next(m for m in result.value["messages"] if m.type == "tool").content
    )
    assert provider_calls == [] and retained(store) == before
