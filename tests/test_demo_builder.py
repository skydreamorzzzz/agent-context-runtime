"""Narrow tests for the static F1 smoke demo projection."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_demo_data import build_demo_data

EVIDENCE_ROOT = Path("docs/receipts/f1_product_core")
CASE_METADATA = Path("demo/cases.json")


def test_builder_projects_committed_f1_smoke_into_demo_view_model() -> None:
    payload = build_demo_data(EVIDENCE_ROOT, cases_path=CASE_METADATA)
    round_trip = json.loads(json.dumps(payload))

    assert round_trip["schema"] == "acr.demo-view/0.1"
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
