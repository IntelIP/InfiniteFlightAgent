"""Controlled retained-route cases; these do not establish navigation validity or live routing."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ifdispatcher import workflow
from ifdispatcher.core import Dispatch, Store

FIXTURE = Path("docs/research/evidence/simbrief-b38m-parser-fixture.json")
ROUTE = "JCOBY4 SWANN PHLBO4"


def prepared(store, route=None, leg="1"):
    store.prepare(
        Dispatch(
            trip="routing",
            leg=leg,
            revision=1,
            origin="KIAD",
            destination="KEWR",
            aircraft="B38M",
            departure="2026-11-09T15:00:00Z",
            units="KGS",
            route=route,
        )
    )
    store.save_meta(
        "routing", leg, 1, {"private_callsign": "N320HD", "prepared_at": "2026-11-09T14:00:00Z"}
    )


def ofp(route=ROUTE, idents=("KIAD", "SWANN", "KEWR")):
    raw = json.loads(FIXTURE.read_text())
    raw["params"]["time_generated"] = datetime.now(timezone.utc).isoformat()
    raw["times"]["sched_out"] = "2026-11-09T15:00:00Z"
    if route is not None:
        raw["general"] = {"route": route}
    if idents is not None:
        raw["navlog"] = {"fix": [{"ident": ident} for ident in idents]}
    return json.dumps(raw).encode()


@pytest.mark.parametrize("approved", [ROUTE, "DCT"])
def test_explicit_route_accepts_case_and_whitespace_only(tmp_path, approved):
    store = Store(tmp_path)
    prepared(store, approved)
    saved = store.save("routing", "1", 1, ofp("  " + approved.lower().replace(" ", "  ")), None)
    assert saved["data"]["flight_route"].strip().upper().split() == approved.split()


@pytest.mark.parametrize(
    "approved,returned", [(ROUTE, "DCT"), (ROUTE, "OTHER ROUTE"), ("DCT", ROUTE)]
)
def test_explicit_route_mismatch_is_not_retained(tmp_path, approved, returned):
    store = Store(tmp_path)
    prepared(store, approved)
    with pytest.raises(ValueError, match="identity_mismatch: route"):
        store.save("routing", "1", 1, ofp(returned), None)
    with pytest.raises(ValueError, match="missing_snapshot"):
        store.read("routing", "1", 1)


@pytest.mark.parametrize("returned", ["DCT", "OTHER ROUTE", None])
def test_automatic_route_must_match_recorded_form_readback(tmp_path, returned):
    store = Store(tmp_path)
    prepared(store)
    meta = store.read_meta("routing", "1", 1)
    meta["generation"] = {"status": "generated", "values": {"route": ROUTE}}
    store.save_meta("routing", "1", 1, meta)
    with pytest.raises(ValueError, match="identity_mismatch: route"):
        store.save("routing", "1", 1, ofp(returned), None)
    with pytest.raises(ValueError, match="missing_snapshot"):
        store.read("routing", "1", 1)


def test_finalize_reports_route_mismatch_without_saving_plan(tmp_path, monkeypatch):
    store = Store(tmp_path)
    prepared(store, ROUTE)
    monkeypatch.setattr(workflow, "_store", lambda: store)
    monkeypatch.setattr(workflow, "fetch_sync", lambda *a, **k: ofp("DCT"))
    result = workflow.finalize_dispatch("routing", "1")
    assert result["status"] == "plan_mismatch"
    assert "route" in result["reason"]
    with pytest.raises(ValueError, match="missing_snapshot"):
        store.read("routing", "1", 1)


def test_route_explanation_uses_each_retained_ofp_not_latest_plan(tmp_path, monkeypatch):
    store = Store(tmp_path)
    for leg, route, idents in [
        ("1", ROUTE, ("KIAD", "SWANN", "KEWR")),
        ("2", "DCT", ("KIAD", "KEWR")),
    ]:
        prepared(store, route if leg == "2" else None, leg)
        if leg == "1":
            meta = store.read_meta("routing", leg, 1)
            meta["generation"] = {"status": "generated", "values": {"route": route}}
            store.save_meta("routing", leg, 1, meta)
        store.save("routing", leg, 1, ofp(route, idents), None)
    monkeypatch.setattr(workflow, "_store", lambda: store)
    monkeypatch.setattr(
        workflow, "fetch_sync", lambda *a, **k: pytest.fail("must use retained OFP")
    )
    for leg, route, count in [("1", ROUTE, 3), ("2", "DCT", 2)]:
        result = workflow.finalize_dispatch("routing", leg)
        assert result["status"] == "complete"
        assert result["synopsis"]["flight_route"] == route
        assert result["synopsis"]["navlog_fix_count"] == count
        assert result["synopsis"]["navlog_idents"][0] == "KIAD"
        assert route in result["briefing_markdown"]
        assert "SimBrief OFP" in result["briefing_markdown"]
        assert "count does not establish route validity" in result["briefing_markdown"]


def test_missing_route_and_navlog_remain_unavailable(tmp_path, monkeypatch):
    store = Store(tmp_path)
    prepared(store)
    store.save("routing", "1", 1, ofp(None, None), None)
    monkeypatch.setattr(workflow, "_store", lambda: store)
    result = workflow.finalize_dispatch("routing", "1")
    assert result["synopsis"]["flight_route"] is None
    assert result["synopsis"]["navlog_fix_count"] is None
    assert result["synopsis"]["navlog_idents"] is None
    assert "Route:** unavailable" in result["briefing_markdown"]
