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
