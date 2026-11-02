"""Thrust estimate tests. B38M uses the real fixture; neo snapshots are SYNTHETIC edits of it."""

import json
from pathlib import Path

import pytest

from ifdispatcher import server
from ifdispatcher.core import Dispatch, normalize, open_store
from ifdispatcher.thrust import estimate_takeoff_n1

FIXTURE = Path("docs/research/evidence/simbrief-b38m-parser-fixture.json")


def synthetic_neo(
    icao="A21N", engines="PW1133G-JM", mode="FLEX", flex="50", oat="15", qnh="29.92", elev="300"
):
    raw = json.loads(FIXTURE.read_text())
    raw["aircraft"].update(icao_code=icao, icaocode=icao, engines=engines)
    conditions = raw["tlr"]["takeoff"]["conditions"]
    conditions.update(temperature=oat, altimeter=qnh)
    runway = next(r for r in raw["tlr"]["takeoff"]["runway"] if r["identifier"] == "30")
    runway.update(thrust_setting=mode, flex_temperature=flex, elevation=elev, bleed_setting="ON")
    return raw


def estimate(raw, **kwargs):
    data = normalize(json.dumps(raw).encode())
    return estimate_takeoff_n1(
        data["aircraft"]["icao_code"],
        data["aircraft"]["engines"],
        data["tlr"]["takeoff"]["conditions"],
        data["selected_takeoff"],
        **kwargs,
    )


def b38m(mode=None, sel=None, oat=None, qnh=None, icao=None):
    raw = json.loads(FIXTURE.read_text())
    runway = next(r for r in raw["tlr"]["takeoff"]["runway"] if r["identifier"] == "30")
    for target, key, value in (
        (runway, "thrust_setting", mode),
        (runway, "flex_temperature", sel),
        (raw["tlr"]["takeoff"]["conditions"], "temperature", oat),
        (raw["tlr"]["takeoff"]["conditions"], "altimeter", qnh),
    ):
        if value is not None:
            target[key] = value
    if icao:
        raw["aircraft"].update(icao_code=icao, icaocode=icao)
    return raw


def test_real_b38m_fixture_d_to2():
    # PA -104 ft, corner 30.2 C, CN1(48)/CN1(15) = 0.9305, TO-2: 0.8**(1/2.7) = 0.9207.
    result = estimate(json.loads(FIXTURE.read_text()))
    data = result["data"]
    assert result["status"] == "estimated"
    assert data["engine"] == "LEAP-1B28"
    assert data["fixed_derate_thrust_fraction"] == 0.2
    assert data["assumed_temperature_c"] == 48.0
    assert data["n1_ratio_to_full_thrust"] == pytest.approx(0.857, abs=0.001)
    low, high = data["n1_ratio_range"]
    assert low < 0.857 < high
    assert any("TO-2 ~20%" in a for a in result["assumptions"])


def test_b38m_matches_earlier_hand_estimate():
    # Report pasted Oct 30: SEL 51, OAT 16, QNH 30.30 -> 0.843 by hand.
    data = estimate(b38m(sel="51", oat="16", qnh="30.30"))["data"]
    assert data["n1_ratio_to_full_thrust"] == pytest.approx(0.843, abs=0.002)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("TO", 1.0),
        ("TO-2", 0.8 ** (1 / 2.7)),
        ("D-TO", 0.9305),
        ("D-TO1", 0.9 ** (1 / 2.7) * 0.9305),
    ],
)
def test_b38m_modes(mode, expected):
    data = estimate(b38m(mode=mode))["data"]
    assert data["n1_ratio_to_full_thrust"] == pytest.approx(expected, abs=0.001)


@pytest.mark.parametrize(
    ("raw", "kwargs", "status"),
    [
        (b38m(mode="TO-B"), {}, "unsupported_thrust_mode"),
        (b38m(mode="D-TO2", sel=""), {}, "missing_input"),
        (b38m(), {"engine_override": "PW1133G-JM"}, "unsupported_profile"),
        (b38m(icao="B738"), {}, "unsupported_profile"),
    ],
)
def test_b38m_explicit_states(raw, kwargs, status):
    assert estimate(raw, **kwargs)["status"] == status


def test_pw1133g_flex_estimate_is_labeled_and_bounded():
    result = estimate(synthetic_neo())
    data = result["data"]
    assert result["status"] == "estimated"
    assert data["engine"] == "PW1133G-JM"
    low, high = data["n1_ratio_range"]
    assert low <= data["n1_ratio_to_full_thrust"] <= high < 1
    assert any("IM.E.093" in s for s in result["sources"])
    assert "simulation-grade estimate" in result["briefing"]


def test_hotter_flex_means_lower_n1():
    cooler = estimate(synthetic_neo(flex="45"))["data"]["n1_ratio_to_full_thrust"]
    hotter = estimate(synthetic_neo(flex="55"))["data"]["n1_ratio_to_full_thrust"]
    assert hotter < cooler < 1


def test_leap1a26_matches_flybywire_hand_calculation():
    # PA 0, OAT 15, FLEX 50, packs on: CN1 = 83.832 - 3.056*6/11 = 82.165; bleed -0.4.
    raw = synthetic_neo(icao="A20N", engines="LEAP-1A26", qnh="1013.25", elev="0")
    data = estimate(raw)["data"]
    assert data["fbw_model_n1"] == 81.8
    assert data["n1_ratio_to_full_thrust"] == pytest.approx(82.165 / 83.832, abs=0.001)


def test_calibration_gives_absolute_target():
    result = estimate(synthetic_neo(), full_thrust_n1=90.0)
    data = result["data"]
    assert data["target_n1"] == round(90.0 * data["n1_ratio_to_full_thrust"], 1)
    assert data["target_n1_range"][0] <= data["target_n1"] <= data["target_n1_range"][1]
    assert f"set N1 {data['target_n1']}%" in result["briefing"]


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"mode": "TOGA"}, "estimated"),
        ({"flex": "25"}, "estimated"),
        ({"mode": "D04"}, "unsupported_thrust_mode"),
        ({"flex": ""}, "missing_input"),
        ({"elev": "5434"}, "unsupported_conditions"),
        ({"qnh": "50"}, "unsupported_conditions"),
        ({"engines": "CFM56-5B4"}, "unsupported_profile"),
    ],
)
def test_explicit_states(changes, status):
    result = estimate(synthetic_neo(**changes))
    assert result["status"] == status
    if changes in ({"mode": "TOGA"}, {"flex": "25"}):
        assert result["data"]["n1_ratio_to_full_thrust"] == 1.0


def test_engine_override_is_recorded():
    result = estimate(synthetic_neo(engines="LEAP-1A33"), engine_override="PW1133G-JM")
    assert result["data"]["engine"] == "PW1133G-JM"
    assert result["data"]["engine_source"] == "user override"


def test_tool_reads_saved_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("IFD_DATA_DIR", str(tmp_path))
    s = open_store()
    s.prepare(
        Dispatch(
            trip="neo",
            leg="out",
            revision=1,
            origin="KIAD",
            destination="KEWR",
            aircraft="A21N",
            departure="2026-10-31T02:10:00Z",
            units="KGS",
        )
    )
    s.save("neo", "out", 1, json.dumps(synthetic_neo()).encode(), None)
    result = server.estimate_takeoff_n1("neo", "out", 1, full_thrust_n1=88.0)
    assert result["status"] == "estimated"
    assert result["data"]["calibration_full_thrust_n1"] == 88.0


def test_support_note_depends_on_the_departure_airport():
    from ifdispatcher.thrust import support_note

    assert "estimate available" in support_note("A21N", "KIAD", 312)
    denver = support_note("A21N", "KDEN", 5434)
    assert "unavailable" in denver and "KDEN (5,434 ft)" in denver
    edge = support_note("A20N", "KXXX", 1600)
    assert "may be unavailable" in edge and "day's pressure" in edge
    assert "elevation of KIAD unknown" in support_note("A21N", "KIAD", None)
    assert "not modeled" in support_note("C172", "KDEN", 5434)


def test_support_note_for_approval_prompts():
    from ifdispatcher.thrust import support_note

    assert "available" in support_note("A21N") and "unavailable" not in support_note("A21N")
    assert "unavailable" in support_note("B789")
