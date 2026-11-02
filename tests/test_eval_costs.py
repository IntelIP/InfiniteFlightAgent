"""No-network checks for paid-test boundaries, replay and metadata caching."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage

from ifdispatcher import agent, flights

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
from flight_data import BudgetExceeded, FlightData  # noqa: E402
from run_eval import run_case  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("IFD_AIRPORT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("IFD_PAID_OPERATIONS_ENABLED", "true")
    monkeypatch.setenv("AEROAPI_KEY", "test-not-a-real-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setattr(flights, "usage", {k: 0 for k in flights.usage})
    monkeypatch.setattr(flights, "_cache", {})
    monkeypatch.setattr(flights, "_recent", [])


def cassette(tmp_path):
    file = tmp_path / "fixture.json"
    file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "synthetic",
                "clock": "2026-10-31T09:13:00+00:00",
                "requests": [
                    {
                        "path": f"/airports/{code}",
                        "params": {},
                        "status_code": 200,
                        "body": {"name": code, "timezone": "America/New_York"},
                    }
                    for code in ("KIAD", "KEWR")
                ],
            }
        )
    )
    return file


def no_network(*args, **kwargs):
    raise AssertionError("network must not be used")


def test_replay_freezes_clock_and_missing_data_invalidates_real_graph(monkeypatch, tmp_path):
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class Model(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    fixture = cassette(tmp_path)
    data = FlightData()
    with data.case(fixture):
        assert agent.current_time.invoke({})["utc"] == "2026-10-31T09:13+00:00"
        assert flights.airport_name("KIAD") == "KIAD"
    case = {
        "id": "TEST",
        "category": "domestic_specific",
        "prompt": "Dulles to Newark",
        "followups": {},
    }
    model = Model(
        messages=iter(
            [
                AIMessage(
                    "",
                    tool_calls=[
                        {"id": "check", "name": "check_airports", "args": {"codes": ["KXXX"]}}
                    ],
                ),
                AIMessage("Which airport?"),
            ]
        )
    )
    result = run_case(case, model, 1, "test", data, fixture)
    assert result["invalid"] and result["fixture_misses"]
    assert result["aeroapi_usd"] == 0 and data.calls == []


def test_replay_reaches_approval_without_generating(monkeypatch, tmp_path):
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class Model(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    model = Model(
        messages=iter(
            [
                AIMessage(
                    "",
                    tool_calls=[
                        {
                            "id": "dispatch",
                            "name": "dispatch_flight",
                            "args": {
                                "trip": "test",
                                "leg": "1",
                                "origin": "KIAD",
                                "destination": "KEWR",
                                "departure_local_date": "2026-10-31",
                                "sim_aircraft": "A20N",
                                "private_callsign": "N123AB",
                                "departure_utc": "2026-10-31T16:00:00Z",
                            },
                        }
                    ],
                )
            ]
        )
    )
    result = run_case(
        {"id": "T", "category": "private_ga", "prompt": "private flight", "followups": {}},
        model,
        1,
        "test",
        fixture=cassette(tmp_path),
    )
    assert not result["invalid"], result
    assert len(result["dispatches"]) == 1 and result["aeroapi_usd"] == 0
    # Airport record reads: name, timezone, elevation (approval summary), plus the dispatch.
    assert result["replay_hits"] == 4


def test_live_prices_pages_records_and_replays_without_network(tmp_path, monkeypatch):
    sent = []

    def send(self, request):
        sent.append(str(request.url))
        return httpx.Response(200, json={"num_pages": 2, "flights": []})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", send)
    data = FlightData("live", "0.15")
    fixture = tmp_path / "recorded.json"
    path = "/airports/KIAD/flights/to/KEWR"
    with data.case(fixture):
        flights._get(path, {"max_pages": 3})
        flights._get(path, {"max_pages": 3})  # cache costs nothing
        with pytest.raises(BudgetExceeded):
            flights._get("/airports/KIAD/flights/to/KDEN", {"max_pages": 3})
    assert len(sent) == 1 and data.charged == 100 and data.held == 0
    assert flights.usage["cost_milliusd"] == 100 and flights.usage["cache_hits"] == 1
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    with FlightData().case(fixture):
        assert flights._get(path, {"max_pages": 3})["num_pages"] == 2


def test_budget_holds_unknown_failures_and_serializes_threads(tmp_path, monkeypatch):
    sent = []

    def send(self, request):
        sent.append(request)
        raise httpx.ReadTimeout("uncertain", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", send)
    data = FlightData("live", "0.005")
    with data.case(tmp_path / "failed.json"):

        def attempt(number):
            try:
                flights._get(f"/flights/UA{number}")
            except ValueError:
                pass

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(attempt, (1, 2)))
    assert len(sent) == 1 and data.held == 5 and data.charged == 0
    assert data.budget_blocked


def test_airport_metadata_persists_and_expires(tmp_path, monkeypatch):
    sent = []
    clock = [1000000.0]
    monkeypatch.setattr(flights.time, "time", lambda: clock[0])

    def send(self, request):
        sent.append(request)
        return httpx.Response(200, json={"name": "Dulles", "timezone": "America/New_York"})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", send)
    assert flights.airport_name("KIAD") == "Dulles"
    flights._cache.clear()  # simulate a fresh process
    assert flights.airport_name("KIAD") == "Dulles"
    assert len(sent) == 1 and flights.usage["cost_milliusd"] == 15
    clock[0] += 7 * 86400 + 1
    flights._cache.clear()
    flights.airport_name("KIAD")
    assert len(sent) == 2


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "0.0001"])
def test_invalid_budget_rejected(amount):
    with pytest.raises(ValueError):
        FlightData("live", amount)


def test_live_recording_replays_clock_clipped_request(tmp_path, monkeypatch):
    def send(self, request):
        if request.url.path.endswith("KIAD"):
            return httpx.Response(200, json={"timezone": "America/New_York", "name": "Dulles"})
        return httpx.Response(200, json={"num_pages": 1, "flights": []})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", send)
    fixture = tmp_path / "clock.json"
    data = FlightData("live")
    with data.case(fixture, clock="2026-10-31T09:13:00+00:00"):
        recorded = flights.find_route_flights("KIAD", "KEWR", "2026-11-02")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    with FlightData().case(fixture):
        assert flights.find_route_flights("KIAD", "KEWR", "2026-11-02") == recorded
    assert data.charged == 65


def test_missing_fixture_never_invokes_model(tmp_path):
    result = run_case(
        {"id": "missing", "category": "edge_cases", "prompt": "test"},
        object(),
        1,
        "test",
        fixture=tmp_path / "absent.json",
    )
    assert result["invalid"] and "FileNotFoundError" in result["error"]
    assert result["aeroapi_usd"] == 0


def test_cli_requires_explicit_live_authorization():
    import subprocess

    root = Path(__file__).resolve().parents[1]
    for script, flags in [("run_eval.py", ["--live"]), ("run_e2e.py", [])]:
        result = subprocess.run(
            [sys.executable, str(root / "evals" / script), *flags],
            capture_output=True,
            text=True,
            cwd=root,
        )
        assert result.returncode == 2 and "requires" in result.stderr


def test_grade_rejects_unobserved_cancelled_and_forbidden_dispatches():
    from run_eval import grade

    case = json.loads(
        (Path(__file__).resolve().parents[1] / "evals/fixtures/synthetic_cases.jsonl")
        .read_text()
        .splitlines()[1]
    )
    run = {
        "error": None,
        "turn_tools": [["find_route_flights"]],
        "transcript": [],
        "dispatches": [
            {
                "origin": "KIAD",
                "destination": "KEWR",
                "fa_flight_id": "invented",
                "before_user_reply": False,
                "sim_aircraft": "A20N",
            }
        ],
    }
    checks = grade(case, run)
    assert not checks["no_dispatch_without_operating_flight"]
    assert not checks["dispatch_flight_grounded"]
    run["transcript"] = [
        {
            "role": "tool",
            "text": json.dumps({"data": [{"fa_flight_id": "invented", "cancelled": True}]}),
        }
    ]
    assert not grade(case, run)["dispatch_flight_grounded"]
