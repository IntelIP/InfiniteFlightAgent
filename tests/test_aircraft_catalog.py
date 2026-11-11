"""Guard research boundaries and fleet math in the frozen catalog."""

import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VALIDATE = runpy.run_path(str(ROOT / "scripts/validate_aircraft_catalog.py"))["validate"]


@pytest.fixture
def catalog():
    return json.loads((ROOT / "docs/research/evidence/aircraft-catalog-v26.json").read_text())


def test_complete_inventory_keeps_legacy_and_icao_collisions(catalog):
    counts = VALIDATE(catalog)
    assert counts["source_records"] == 62
    assert counts["current_fleet"] == 51
    assert counts["legacy_excluded"] == 11
    assert counts["strict_majority"] == 26
    assert counts["verified_supported"] == 0
    rows = {r["id"]: r for r in catalog["records"]}
    assert rows["777f"]["icao_from_fleet"] == rows["777-200lr"]["icao_from_fleet"]
    assert rows["777f"]["simbrief"]["id"] == "B77F"
    assert rows["e175"]["icao_from_fleet"] == "E75L"
    assert rows["e175"]["simbrief"]["id"] == "E175"
    assert rows["challenger-350"]["simbrief"]["tlr_data"] is True
    assert "torque" in rows["dash-8-q400"]["target_investigation_candidates"]
    assert "manifold_pressure" in rows["172"]["target_investigation_candidates"]


@pytest.mark.parametrize("fault", ["drop_legacy", "duplicate", "majority", "source", "ota_build"])
def test_invalid_inventory_and_source_changes_are_rejected(catalog, fault):
    if fault == "drop_legacy":
        catalog["records"] = [r for r in catalog["records"] if not r["legacy"]]
    elif fault == "duplicate":
        catalog["records"].append(catalog["records"][0])
    elif fault == "majority":
        catalog["denominator"]["strict_majority"] = 25
    elif fault == "source":
        catalog["records"][0]["native"]["source_refs"] = ["unknown"]
    else:
        next(c for c in catalog["changes"] if c["kind"] == "ota")["build"] = 20344
    with pytest.raises(ValueError):
        VALIDATE(catalog)


@pytest.mark.parametrize("fault", ["target", "support", "performance"])
def test_research_cannot_be_promoted_into_observed_support(catalog, fault):
    row = catalog["records"][0]
    if fault == "target":
        row["displayed_target_type"] = "N1"
    elif fault == "support":
        row["support_verified"] = True
        catalog["denominator"]["verified_supported"] += 1
    else:
        row["simbrief"]["id"] = None
        row["simbrief"]["tlr_data"] = True
    with pytest.raises(ValueError):
        VALIDATE(catalog)
