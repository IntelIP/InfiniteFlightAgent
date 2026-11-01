"""Live acceptance decisions (scripts/acceptance.py) on SYNTHETIC records, not live evidence."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import acceptance  # noqa: E402


def leg(number, clicked, retrieved, sha, aircraft="A21N", status="generated"):
    return {
        "leg": number,
        "revision": 1,
        "requested": {"origin": "KIAD", "destination": "KDEN", "aircraft": aircraft},
        "generation": {"status": status, "clicked_at": clicked, "browser_session": True},
        "snapshot": {
            "sha256": sha,
            "retrieved_at": retrieved,
            "generated_at": clicked.replace("00.0", "05.0"),
            "origin": "KIAD",
            "destination": "KDEN",
            "aircraft": aircraft,
            "takeoff_status": "available",
        },
    }


def case(*legs, interrupts=1, resumes=1):
    return {
        "thread": "t",
        "trip": "T",
        "interrupts": interrupts,
        "resumes": resumes,
        "legs": list(legs),
    }


FIRST = leg("1", "2026-11-01T21:00:00.0+00:00", "2026-11-01T21:02:00+00:00", "a")
SECOND = leg("2", "2026-11-01T21:10:00.0+00:00", "2026-11-01T21:12:00+00:00", "b")


def test_two_retained_neo_legs_after_approval_show_every_outcome():
    shown = acceptance.outcomes([case(FIRST, SECOND)])
    assert all(outcome["passed"] for outcome in shown.values()), shown


def test_one_leg_does_not_show_two_legs_retained():
    shown = acceptance.outcomes([case(FIRST)])
    assert shown["generation_through_mcp"]["passed"]
    assert not shown["two_legs_retained"]["passed"]


def test_uncertain_or_mismatched_generation_counts_for_nothing():
    uncertain = leg(
        "1", "2026-11-01T21:00:00.0+00:00", "2026-11-01T21:02:00+00:00", "a", status="uncertain"
    )
    mismatched = leg("2", "2026-11-01T21:10:00.0+00:00", "2026-11-01T21:12:00+00:00", "b")
    mismatched["snapshot"]["destination"] = "KSFO"
    shown = acceptance.outcomes([case(uncertain, mismatched)])
    assert not any(outcome["passed"] for outcome in shown.values())


def test_no_approval_wait_does_not_show_resumption():
    shown = acceptance.outcomes([case(FIRST, SECOND, interrupts=0)])
    assert not shown["authentication_and_resumption"]["passed"]


def test_non_neo_aircraft_does_not_show_a_neo_response():
    older = leg(
        "1", "2026-11-01T21:00:00.0+00:00", "2026-11-01T21:02:00+00:00", "a", aircraft="A320"
    )
    assert not acceptance.outcomes([case(older)])["neo_response"]["passed"]


def test_gap_requires_evidence_every_outcome_and_unchanged_code(tmp_path, monkeypatch):
    evidence = tmp_path / "live-acceptance.json"
    monkeypatch.setattr(acceptance, "EVIDENCE", evidence)
    assert "No live acceptance evidence" in acceptance.gap()

    shown = acceptance.outcomes([case(FIRST)])
    record = {"deployment": {"commit": "abc1234def"}, "outcomes": shown}
    evidence.write_text(
        json.dumps({**record, "integration_digest": acceptance.integration_digest()})
    )
    assert "two_legs_retained not shown" in acceptance.gap()

    shown = acceptance.outcomes([case(FIRST, SECOND)])
    evidence.write_text(json.dumps({**record, "outcomes": shown, "integration_digest": "old"}))
    assert (
        acceptance.gap() == "Integration code changed since live acceptance on abc1234; repeat it."
    )

    evidence.write_text(
        json.dumps(
            {**record, "outcomes": shown, "integration_digest": acceptance.integration_digest()}
        )
    )
    assert acceptance.gap() is None
