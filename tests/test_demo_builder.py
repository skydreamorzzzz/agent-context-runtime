"""Narrow tests for the static F1 smoke demo projection."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_demo_data import build_demo_data, step_status

EVIDENCE_ROOT = Path("docs/receipts/f1_product_core")
CASE_METADATA = Path("demo/cases.json")


def test_builder_projects_committed_f1_smoke_into_demo_view_model() -> None:
    payload = build_demo_data(EVIDENCE_ROOT, cases_path=CASE_METADATA)
    round_trip = json.loads(json.dumps(payload))

    assert round_trip["schema"] == "acr.demo-view/0.2"
    assert round_trip["skipped_sessions"] == []
    assert len(round_trip["sessions"]) == 1
    session = round_trip["sessions"][0]
    assert session["presentation"]["title"] == "Calculator regression"
    assert session["last_pass"]["exit_code"] == 0
    assert session["first_fail"]["exit_code"] == 1
    assert session["last_pass"]["manifest_hash"] != session["first_fail"]["manifest_hash"]
    assert [item["path"] for item in session["changed_files"]] == ["calculator.py"]
    assert session["changed_files"][0]["change_type"] == "modified"
    assert "-    return a + b" in session["changed_files"][0]["diff"]
    assert "+    return a - b" in session["changed_files"][0]["diff"]
    assert session["observed_activity"] == [
        {
            "event_count": 2,
            "kind": "Bash",
            "label": "Bash operation",
            "sequence": 6,
        }
    ]
    assert session["summary"]["overall_status"] == "red"
    assert session["overall_status"] == "red"
    assert session["summary"]["diagnostic_warning_count"] == 0
    assert {item["rule"] for item in session["diagnostics"]} == {
        "W01", "W02", "W03", "W04", "W05", "W06", "W07", "W08"
    }
    assert session["diagnostics"][0]["status"] == "not_evaluated"
    assert all(item["status"] == "not_evaluated" for item in session["diagnostics"])
    assert all(item["event_sequences"] == [] for item in session["diagnostics"])
    assert [item["kind"] for item in session["timeline"]] == [
        "verified_pass", "observed_activity", "repository_transition", "verified_fail"
    ]
    assert [item["status"] for item in session["timeline"]] == [
        "green", "neutral", "neutral", "red"
    ]
    assert all(item["diagnostic_refs"] == [] for item in session["timeline"])
    assert session["evidence_integrity"]["status"] == "verified"
    assert all(item["status"] == "pass" for item in session["evidence_integrity"]["checks"])
    assert session["privacy_boundary"]["status"] == "enforced"


def test_step_status_has_explicit_priority() -> None:
    assert step_status({"has_verified_success": True}) == "green"
    assert step_status({"diagnostic_refs": [{"rule": "W04"}]}) == "yellow"
    assert step_status({"has_verified_failure": True, "diagnostic_refs": [{"rule": "W06"}]}) == "red"
    assert step_status({}) == "neutral"
    assert step_status({"diagnostic_refs": [], "is_normal_observed_operation": False}) == "neutral"


def test_presentation_diagnostic_binds_to_concrete_timeline_step() -> None:
    session = build_demo_data(EVIDENCE_ROOT, cases_path=CASE_METADATA)["sessions"][0]
    bound = build_session_view_with_metadata(
        {
            "diagnostics": {
                "W06": {
                    "status": "warning",
                    "severity": "yellow",
                    "summary": "Repeated command pattern observed",
                    "occurrences": 1,
                    "event_sequences": [6],
                }
            }
        }
    )
    step = next(item for item in bound["timeline"] if item["sequence"] == 6)
    assert step["status"] == "yellow"
    assert step["diagnostic_refs"] == [
        {
            "rule": "W06",
            "title": "Repeated Command",
            "summary": "Repeated command pattern observed",
        }
    ]
    assert session["timeline"][1]["status"] == "neutral"


def build_session_view_with_metadata(metadata: dict[str, object]) -> dict[str, object]:
    from scripts.build_demo_data import build_session_view

    return build_session_view(
        EVIDENCE_ROOT,
        "session-6886bc4f40144176bb747ba0556a02d0",
        metadata,
    )


def test_session_warning_without_event_sequences_does_not_color_step() -> None:
    session = build_session_view_with_metadata(
        {
            "diagnostics": {
                "W01": {
                    "status": "warning",
                    "severity": "yellow",
                    "summary": "Session-level signal",
                }
            }
        }
    )
    assert session["summary"]["diagnostic_warning_count"] == 1
    assert [item["status"] for item in session["timeline"]] == [
        "green", "neutral", "neutral", "red"
    ]
