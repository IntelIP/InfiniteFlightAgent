"""AeroAPI normalization tests. AeroAPI responses here are SYNTHETIC (mocked _get)."""

from ifdispatcher import flights


def occurrence(day, gate, actual_out=True, origin="KIAD"):
    return {
        "ident_iata": "UA495",
        "origin": {"code_icao": origin, "timezone": "America/New_York"},
        "scheduled_out": f"2026-10-{day}T02:10:00Z",
        "actual_out": f"2026-10-{day}T02:15:00Z" if actual_out else None,
        "gate_origin": gate,
        "aircraft_type": "A21N",
        "registration": "N14507",
    }


def test_recent_gates_uses_latest_completed_occurrence_with_gate(monkeypatch):
    rows = [
        occurrence(27, "B26"),
        occurrence(29, "C27"),
        occurrence(30, None),  # completed but no gate recorded
        occurrence(31, "C9", actual_out=False),  # not departed yet
        occurrence(28, "Z1", origin="KBDL"),  # other leg of the same number
    ]
    monkeypatch.setattr(flights, "_get", lambda path, params=None: {"flights": rows})
    result = flights.recent_gates("UA495", "KIAD")
    assert result["status"] == "ok"
    assert result["data"]["most_recent"]["gate"] == "C27"
    assert result["data"]["most_recent"]["date_local"] == "2026-10-28"  # 02:10Z = prior evening EDT
    assert [r["gate"] for r in result["data"]["recent"]] == ["C27", "B26"]
    assert "not an assignment" in result["note"]


def test_recent_gates_none_found(monkeypatch):
    monkeypatch.setattr(flights, "_get", lambda path, params=None: {"flights": []})
    assert flights.recent_gates("UA495", "KIAD")["status"] == "no_flights"


def test_kill_switch_blocks_flightaware_and_fails_closed(monkeypatch):
    flights._cache.clear()
    for value in ("false", "maybe"):
        monkeypatch.setenv("IFD_PAID_OPERATIONS_ENABLED", value)
        try:
            flights._get("/airports/KIAD")
        except ValueError as exc:
            assert "paid_operations_disabled" in str(exc)
        else:
            raise AssertionError("kill switch did not block the call")


def test_rate_limiter_waits_instead_of_exceeding(monkeypatch):
    slept = []
    clock = [1000.0]
    monkeypatch.setattr(flights.time, "monotonic", lambda: clock[0])

    def fake_sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(flights.time, "sleep", fake_sleep)
    flights._recent[:] = [(clock[0] - 10, 9)]  # 9 sets used 10 s ago
    flights._wait_for_rate_limit(3)  # would make 12 > 10
    assert slept and 50 <= slept[0] <= 51
    flights._recent.clear()
