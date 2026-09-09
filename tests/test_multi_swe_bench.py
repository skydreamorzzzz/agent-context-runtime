"""Offline tests for the fixed Multi-SWE-bench Flash OpenHands adapter."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from acr.adapters.multi_swe_bench import ADAPTER_VERSION, adapt_trajectory
from acr.candidates import detect_duplicate_reads
from acr.coverage import (
    ARCHIVE_PATH,
    DATASET_NAME,
    DATASET_REVISION,
    audit_coverage_report,
    scan_archive,
)


def _events(*, include_edit: bool = False) -> list[dict]:
    path = "/workspace/org__repo__0.1/target.py"
    content = (
        "Here's the result of running `cat -n` on "
        f"{path}:\n     1\tdef add(a, b):\n     2\t    pass\n"
    )
    events: list[dict] = []
    for identifier in (10, 20):
        events.extend(
            [
                {
                    "id": identifier,
                    "timestamp": "2025-07-25T00:00:00",
                    "source": "agent",
                    "message": f"Reading file: {path}",
                    "action": "read",
                    "args": {
                        "path": path,
                        "start": 0,
                        "end": -1,
                        "view_range": None,
                    },
                    "tool_call_metadata": {
                        "model_response": {
                            "id": f"response-{identifier}",
                            "usage": {"prompt_tokens": identifier},
                        }
                    },
                },
                {
                    "id": identifier + 1,
                    "timestamp": "2025-07-25T00:00:01",
                    "source": "agent",
                    "message": f"I read the file {path}.",
                    "cause": identifier,
                    "observation": "read",
                    "content": content,
                    "extras": {"path": path},
                },
            ]
        )
        if identifier == 10 and include_edit:
            events.extend(
                [
                    {
                        "id": 15,
                        "timestamp": "2025-07-25T00:00:02",
                        "source": "agent",
                        "message": "Editing file",
                        "action": "edit",
                        "args": {"path": path, "command": "str_replace"},
                    },
                    {
                        "id": 16,
                        "timestamp": "2025-07-25T00:00:03",
                        "source": "agent",
                        "message": "I edited the file.",
                        "cause": 15,
                        "observation": "edit",
                        "content": "edited",
                        "extras": {"path": path},
                    },
                ]
            )
    return events


def _raw(*, include_edit: bool = False) -> bytes:
    return json.dumps(_events(include_edit=include_edit), separators=(",", ":")).encode()


def _source(raw_archive: bytes) -> dict:
    return {
        "dataset_name": DATASET_NAME,
        "dataset_revision": DATASET_REVISION,
        "archive_path": ARCHIVE_PATH,
        "archive_size": len(raw_archive),
        "archive_sha256": hashlib.sha256(raw_archive).hexdigest(),
        "archive_commit": "fixture-commit",
        "expected_trajectory_members": 1,
        "adapter_version": ADAPTER_VERSION,
        "retrieved_on": "2026-09-09",
        "license_note": "synthetic engineering fixture",
        "usage_note": "offline test",
    }


def test_adapter_preserves_source_positions_occurrences_and_exact_output() -> None:
    raw = _raw()
    trajectory = adapt_trajectory(raw, "org__repo-1")
    first, second = trajectory.read_occurrences
    assert first.normalized_path == second.normalized_path == "target.py"
    assert first.source_position == 0
    assert second.source_position == 2
    assert first.occurrence_id != second.occurrence_id
    assert first.output_sha256 == second.output_sha256
    assert first.evidence_refs[0].locator == "/0"
    assert first.evidence_refs[1].locator == "/1/content"
    assert first.file_sha256 is None
    assert first.encoding is None
    assert first.request_membership_observed is None
    assert trajectory.observed_input_tokens == 30


def test_real_format_missing_file_identity_stays_unknown_and_edit_rejects() -> None:
    clean = adapt_trajectory(_raw(), "org__repo-1")
    clean_result = detect_duplicate_reads(
        clean.read_occurrences, clean.changes, event_count=clean.event_count
    )[0]
    changed = adapt_trajectory(_raw(include_edit=True), "org__repo-1")
    changed_result = detect_duplicate_reads(
        changed.read_occurrences, changed.changes, event_count=changed.event_count
    )[0]
    assert (clean_result.status, clean_result.reason) == ("unknown", "file_encoding_unobserved")
    assert (changed_result.status, changed_result.reason) == (
        "rejected",
        "intervening_file_change",
    )


def test_adapter_rejects_malformed_event_identity() -> None:
    events = _events()
    events[1]["id"] = events[0]["id"]
    with pytest.raises(ValueError, match="event identity"):
        adapt_trajectory(json.dumps(events).encode(), "org__repo-1")


def test_archive_scan_and_persisted_report_audit_are_reproducible(tmp_path: Path) -> None:
    archive_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("root/trajs/org__repo-1/trajectory.json", _raw())
    archive_bytes = archive_path.read_bytes()
    source = _source(archive_bytes)
    report = scan_archive(archive_path, source)
    assert report.metrics["total_trajectories"] == 1
    assert report.metrics["exact_content_duplicate_count"] == 1
    assert report.metrics["strict_candidate_count"] == 0
    assert report.verdict == "NO_GO"
    assert audit_coverage_report(report, archive_path, source).status == "PASS"

    tampered = report.model_copy(
        update={"metrics": {**report.metrics, "strict_candidate_count": 1}}
    )
    audit = audit_coverage_report(tampered, archive_path, source)
    assert audit.status == "BLOCK"
    assert "coverage_report_mismatch" in audit.blocks
