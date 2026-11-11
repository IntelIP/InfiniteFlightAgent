"""v0.4.5 software contracts; numerical/simulator accuracy needs independent evidence."""

import copy
import json
from pathlib import Path

import pytest

from ifdispatcher import operations, thrust, workflow
from ifdispatcher.core import Dispatch, Store, normalize

MANIFEST = json.loads(Path("evals/thrust_cases_v045.json").read_text())
FIXTURE = Path("docs/research/evidence/simbrief-b38m-parser-fixture.json")


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=lambda c: c["id"] + "-" + c["name"])
def test_profile_and_condition_contract(case):
    result = thrust.estimate_takeoff_n1(**case["input"])
    assert result["status"] == case["expected"]["status"]
    if "engine" in case["expected"]:
        assert result["data"]["engine"] == case["expected"]["engine"]
    if result["status"] == "estimated":
        data = result["data"]
        assert (
            0
            < data["n1_ratio_range"][0]
            <= data["n1_ratio_to_full_thrust"]
            <= data["n1_ratio_range"][1]
            <= 1
        )
    else:
        assert "data" not in result and "briefing" not in result


def calibration_data():
    return normalize(FIXTURE.read_bytes())


def calculated(data, reading=None):
    return thrust.estimate_takeoff_n1(
        data["aircraft"]["icao_code"],
        data["aircraft"]["engines"],
        data["tlr"]["takeoff"]["conditions"],
        data["selected_takeoff"],
        full_thrust_n1=reading,
    )


def test_calibration_does_not_cross_weight_units(tmp_path):
    store = Store(tmp_path)
    data = calibration_data()
    _, saved = operations.calibrated_estimate(
        store, data, None, calculated(data, 92), 92, "26.5.2/build20344"
    )
    assert saved["status"] == "saved"
    changed = copy.deepcopy(data)
    changed["weight_units"] = "lbs" if data["weight_units"] == "kgs" else "kgs"
    result, calibration = operations.calibrated_estimate(
        store, changed, None, calculated(changed), None, "26.5.2/build20344"
    )
    assert calibration["status"] == "reading_needed"
    assert "target_n1" not in result["data"]


@pytest.mark.parametrize(
    "corruption", ["bad-json", "bad-time", "naive-time", "wrong-scope", "bad-reading"]
)
def test_bad_saved_calibration_keeps_uncalibrated_briefing(tmp_path, corruption):
    store = Store(tmp_path)
    data = calibration_data()
    operations.calibrated_estimate(store, data, None, calculated(data, 92), 92, "26.5.2/build20344")
    with store.connect() as db:
        key, raw = db.execute("SELECT name,value FROM settings").fetchone()
    record = json.loads(raw)
    if corruption == "bad-time":
        record["observed_at"] = "not a timestamp"
    elif corruption == "naive-time":
        record["observed_at"] = "2026-11-11T12:00:00"
    elif corruption == "wrong-scope":
        record["scope"]["simulator_version"] = "25.0"
    elif corruption == "bad-reading":
        record["full_thrust_n1"] = "invalid N1"
    store.save_setting(key, "{broken" if corruption == "bad-json" else json.dumps(record))
    result, calibration = operations.calibrated_estimate(
        store, data, None, calculated(data), None, "26.5.2/build20344"
    )
    assert calibration["status"] == "reading_needed"
    assert result["status"] == "estimated" and "target_n1" not in result["data"]


@pytest.mark.parametrize("engine", ["LEAP-1B28B1", "LEAP-1B28UNKNOWN"])
def test_unmodeled_engine_retains_ofp_but_withholds_saved_briefing_target(
    tmp_path, monkeypatch, engine
):
    store = Store(tmp_path)
    raw = json.loads(FIXTURE.read_text())
    raw["aircraft"]["engines"] = engine
    raw.setdefault("general", {})["route"] = "DCT"
    store.prepare(
        Dispatch(
            trip="v045",
            leg="1",
            revision=1,
            origin=raw["origin"]["icao_code"],
            destination=raw["destination"]["icao_code"],
            aircraft="B38M",
            departure="2026-11-13T12:00:00Z",
            route="DCT",
        )
    )
    snap = store.save("v045", "1", 1, json.dumps(raw).encode(), None)
    monkeypatch.setattr(workflow, "_store", lambda: store)
    monkeypatch.setattr(
        workflow, "fetch_sync", lambda *a, **k: pytest.fail("must use retained OFP")
    )
    result = workflow.finalize_dispatch("v045", "1")
    assert result["status"] == "complete"
    assert result["thrust"]["status"] == "unsupported_profile"
    assert "unavailable" in result["briefing_markdown"]
    assert "set N1" not in result["briefing_markdown"]
    assert result["snapshot"]["sha256"] == snap["raw_sha256"]
    assert store.read_meta("v045", "1", 1)["briefing"] == result["briefing_markdown"]


REFERENCE = json.loads(Path("docs/research/evidence/thrust-v045-reference.json").read_text())


@pytest.mark.parametrize("case", REFERENCE["cases"], ids=lambda c: c["id"])
def test_leap1a26_port_against_independently_executed_pinned_cpp(case):
    actual = thrust.fbw_leap1a26_n1(
        case["pressure_altitude_ft"],
        case["oat_c"],
        case["flex_c"],
        case["packs"],
        case["nacelle_anti_ice"],
        case["wing_anti_ice"],
    )
    assert actual == pytest.approx(
        case["source_n1_percent"], abs=REFERENCE["raw_tolerance_n1_percentage_points"]
    )


@pytest.mark.parametrize("field,value", [("planned_weight", "72000"), ("wind_speed", "18")])
def test_calibration_changes_in_plan_conditions_require_new_reading(tmp_path, field, value):
    store = Store(tmp_path)
    data = calibration_data()
    operations.calibrated_estimate(store, data, None, calculated(data, 92), 92, "26.5.2/build20344")
    changed = copy.deepcopy(data)
    changed["tlr"]["takeoff"]["conditions"][field] = value
    result, calibration = operations.calibrated_estimate(
        store, changed, None, calculated(changed), None, "26.5.2/build20344"
    )
    assert calibration["status"] == "reading_needed" and "target_n1" not in result["data"]


def test_saved_briefing_keeps_method_assumptions_and_sources(tmp_path, monkeypatch):
    store = Store(tmp_path)
    raw = json.loads(FIXTURE.read_text())
    raw.setdefault("general", {})["route"] = "DCT"
    store.prepare(
        Dispatch(
            trip="v045",
            leg="1",
            revision=1,
            origin=raw["origin"]["icao_code"],
            destination=raw["destination"]["icao_code"],
            aircraft="B38M",
            departure="2026-11-13T12:00:00Z",
            route="DCT",
        )
    )
    store.save("v045", "1", 1, json.dumps(raw).encode(), None)
    monkeypatch.setattr(workflow, "_store", lambda: store)
    result = workflow.finalize_dispatch("v045", "1")
    text = result["briefing_markdown"]
    assert result["thrust"]["method"] in text
    assert all(a in text for a in result["thrust"]["assumptions"])
    assert all(s in text for s in result["thrust"]["sources"])
