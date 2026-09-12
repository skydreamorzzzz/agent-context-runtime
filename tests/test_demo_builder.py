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
    assert session["presentation"]["title"] == "Calculator Regression · Baseline"
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
            "source": "demo presentation metadata",
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


def test_demo_raw_hit_correlates_exactly_to_f1_occurrence(tmp_path: Path) -> None:
    raw_session = tmp_path / "session-6886bc4f40144176bb747ba0556a02d0"
    (raw_session / "normalized").mkdir(parents=True)
    (raw_session / "diagnostics").mkdir()
    (raw_session / "metadata.json").write_text(
        json.dumps({"source_hash": "a" * 64})
    )
    occurrence_id = "call_00_izUXyuwVhQB9ZBVu5Sy48960"
    (raw_session / "normalized" / "steps.json").write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "sequence": 4,
                        "kind": "tool",
                        "tool": "Bash",
                        "occurrence_id": occurrence_id,
                        "input": {"command": "git status --short"},
                    }
                ]
            }
        )
    )
    (raw_session / "diagnostics" / "hits.json").write_text(
        json.dumps(
            {
                "hits": [
                    {
                        "diagnostic_id": "exact_repeated_command_v1",
                        "event_sequence": 4,
                        "occurrence_id": occurrence_id,
                        "rule_family": "W06-compatible",
                        "source_class": "demo_raw",
                        "summary": "Exact command repeated",
                    }
                ]
            }
        )
    )
    from scripts.build_demo_data import build_session_view

    session = build_session_view(
        EVIDENCE_ROOT,
        "session-6886bc4f40144176bb747ba0556a02d0",
        {},
        raw_session,
    )
    step = next(item for item in session["timeline"] if item["sequence"] == 6)
    assert step["status"] == "yellow"
    assert step["diagnostic_refs"][0]["rule"] == "D02"
    assert step["diagnostic_refs"][0]["source"] == "demo_raw_derived"
    assert session["raw_trajectory"]["correlation_status"] == "exact"
    assert [item["path"] for item in session["changed_files"]] == ["calculator.py"]


def test_committed_demo_cases_cover_real_red_yellow_and_green() -> None:
    payload = build_demo_data(
        EVIDENCE_ROOT,
        cases_path=CASE_METADATA,
        artifacts_root=Path("demo/case-artifacts"),
    )
    assert len(payload["sessions"]) >= 4
    artifacts = [item for item in payload["sessions"] if item.get("artifact")]
    assert len(artifacts) >= 3
    assert {item["overall_status"] for item in artifacts} >= {"red", "yellow", "green"}

    red = next(item for item in artifacts if item["overall_status"] == "red")
    yellow = next(item for item in artifacts if item["overall_status"] == "yellow")
    green = next(item for item in artifacts if item["overall_status"] == "green")
    assert red["end_verification"]["outcome"] == "fail"
    assert red["end_verification"]["exit_code"] != 0
    yellow_steps = [item for item in yellow["timeline"] if item["status"] == "yellow"]
    assert yellow_steps
    assert yellow_steps[0]["diagnostic_refs"][0]["source"] == "demo_raw_derived"
    assert yellow["artifact"]["source_class"] == "demo_raw_derived"
    d02 = next(item for item in yellow["diagnostics"] if item["rule"] == "D02")
    assert d02["event_sequences"]
    assert d02["related_event_sequences"]
    assert green["end_verification"] == green["final_pass"]
    assert green["end_verification"]["exit_code"] == 0
    assert green["changed_files"]
    assert any("Baseline" in item["presentation"]["title"] for item in payload["sessions"])


def test_committed_artifacts_exclude_raw_trajectory_bodies() -> None:
    forbidden_keys = {"body", "input", "output", "prompt", "response", "transcript_path"}

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    for path in Path("demo/case-artifacts").glob("*.json"):
        text = path.read_text()
        artifact = json.loads(text)
        assert forbidden_keys.isdisjoint(keys(artifact))
        assert "/home/" not in text
        assert "/.claude/" not in text
        assert artifact["provenance"]["real_capture"] is True
        assert artifact["provenance"]["raw_committed"] is False


def test_frontend_case_selector_renders_status_marked_multiple_cases() -> None:
    html = Path("demo/index.html").read_text()
    javascript = Path("demo/app.js").read_text()
    assert 'id="session-select"' in html
    assert "sessions.length <= 1" in javascript
    assert all(marker in javascript for marker in ("🔴", "🟡", "🟢"))
