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
        ({"elev": "5434"}, "estimated"),  # Denver: inside FlyByWire's -2000..16600 ft table
        ({"elev": "18000"}, "unsupported_conditions"),
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
    assert "estimate available" in denver and "KDEN (5,434 ft)" in denver
    edge = support_note("A20N", "SLLP", 16000)
    assert "may be unavailable" in edge and "day's pressure" in edge
    too_high = support_note("A20N", "XXXX", 18000)
    assert "unavailable (outside the modeled -2,000..16,600 ft" in too_high
    assert "elevation of KIAD unknown" in support_note("A21N", "KIAD", None)
    assert "not modeled" in support_note("C172", "KDEN", 5434)


def test_support_note_for_approval_prompts():
    from ifdispatcher.thrust import support_note

    assert "available" in support_note("A21N") and "unavailable" not in support_note("A21N")
    assert "unavailable" in support_note("B789")


def fbw_limit_n1_reference(altitude, oat, flex, packs, nacelle, wing):
    """FlyByWire ThrustLimits_A32NX::limitN1 for TO at Mach 0, transcribed line by line."""
    from ifdispatcher.thrust import FBW_TO as limits

    rows = range(len(limits))
    if altitude <= limits[0][0]:
        lo = hi = 0
    elif altitude >= limits[-1][0]:
        lo = hi = len(limits) - 1
    else:
        hi = next(r for r in rows if limits[r][0] > altitude)
        lo = hi - 1

    def interp(col):
        x0, x1 = limits[lo][0], limits[hi][0]
        if x0 == x1:
            return limits[lo][col]
        return limits[lo][col] + (altitude - x0) * (limits[hi][col] - limits[lo][col]) / (x1 - x0)

    cp, lp, cn1_flat, cn1_last, cn1_flex = (interp(c) for c in range(1, 6))
    if flex > 0:
        if flex <= cp:
            cn1 = cn1_flat
        elif flex > lp:
            m = (cn1_flex - cn1_last) / (100 - lp)
            cn1 = m * flex + (cn1_flex - m * 100)
        else:
            m = (cn1_last - cn1_flat) / (lp - cp)
            cn1 = m * flex + (cn1_last - m * lp)
    elif oat <= cp:
        cn1 = cn1_flat
    else:
        m = (cn1_last - cn1_flat) / (lp - cp)
        cn1 = m * oat + (cn1_last - m * lp)
    if flex > lp:
        bleed = packs * -0.6 + nacelle * -0.7 + wing * -0.7
    else:
        table = {
            (True, True): (-0.4, -0.6, -0.7),
            (True, False): (-0.5, -0.6, -0.7),
            (False, True): (-0.6, -0.8, -0.8),
            (False, False): (-0.7, -0.8, -0.8),
        }
        p, n, w = table[(altitude < 8000, oat < cp)]
        bleed = packs * p + nacelle * n + wing * w
    return cn1 * ((273.15 + oat) / 288.15) ** 0.5 + bleed


@pytest.mark.parametrize("altitude", [-1500, 0, 1500, 2500, 5456, 7999, 8000, 9500, 13000, 16600])
@pytest.mark.parametrize(("oat", "flex"), [(-10, 0), (15, 0), (35, 0), (10, 30), (20, 60)])
@pytest.mark.parametrize("bleeds", [(0, 0, 0), (1, 1, 1)])
def test_fbw_port_matches_flybywire_formula_at_every_altitude(altitude, oat, flex, bleeds):
    from ifdispatcher.thrust import fbw_leap1a26_n1

    ours = fbw_leap1a26_n1(altitude, oat, flex or None, *bleeds)
    assert ours == pytest.approx(fbw_limit_n1_reference(altitude, oat, flex, *bleeds), abs=1e-9)


def test_high_altitude_estimate_is_labeled_and_wider_than_sea_level():
    sea = estimate(synthetic_neo(elev="300", flex="40", oat="10"))
    denver = estimate(synthetic_neo(elev="5434", flex="40", oat="10"))
    assert sea["status"] == denver["status"] == "estimated"
    width = {
        k: r["data"]["n1_ratio_range"][1] - r["data"]["n1_ratio_range"][0]
        for k, r in (("sea", sea), ("denver", denver))
    }
    assert width["denver"] > width["sea"]
    assert any("extrapolated with FlyByWire's LEAP-1A26 lapse" in n for n in denver["notes"])
    assert any("EASA E.110" in a for a in denver["assumptions"])
    assert not any("EASA E.110" in a for a in sea["assumptions"])


def test_no_high_altitude_widening_at_or_below_2000_ft():
    # Below 2,000 ft v0.3.0 matches v0.2.1 exactly (270 cases compared when the table grew).
    for elev in ("-1500", "300", "1900"):
        result = estimate(synthetic_neo(elev=elev))
        assert result["status"] == "estimated"
        assert not any("EASA E.110" in a for a in result["assumptions"])


def test_warnings_are_printed_in_the_briefing_line_most_serious_first():
    # Like the live Denver plan (FLEX 43-47 C, OAT 9-11 C, ~5,500 ft): both warnings fire.
    denver = estimate(synthetic_neo(elev="5500", flex="45", oat="9"))
    line = denver["briefing"]
    assert denver["warnings"] == [
        "SUSPECT: thrust reduction over the 25% FAA AC 25-13 limit",
        "high altitude (5,501 ft): engine behavior extrapolated, wider range",  # 29.92 inHg
    ]
    assert line.endswith(" — " + "; ".join(denver["warnings"]))
    assert line.index("SUSPECT") < line.index("high altitude")


def test_ordinary_estimate_has_no_warnings():
    sea = estimate(synthetic_neo(elev="300", flex="50", oat="15"))
    assert sea["warnings"] == []
    assert " — " not in sea["briefing"]
