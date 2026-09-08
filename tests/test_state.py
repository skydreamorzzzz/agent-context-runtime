"""Current file verification against an exact historical read binding."""

from __future__ import annotations

import json
from pathlib import Path

from acr.runtime.runner import CapturedRuntime, RuntimeTask


def _bound_file(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "target.py"
    raw = b"def add(a, b):\n    pass\n"
    path.write_bytes(raw)
    data_root = tmp_path / "data"
    runtime = CapturedRuntime(
        data_root=data_root,
        run_id="run-1",
        task=RuntimeTask("public/add", "public"),
        workspace=workspace,
        config_bytes=b"{}",
    )
    read = runtime.tools.read_file("target.py")
    return runtime, data_root, path, read.binding, read.body_ref


def test_compare_file_reports_same_then_changed_from_current_bytes(tmp_path: Path) -> None:
    runtime, data_root, path, binding, ref = _bound_file(tmp_path)
    same = runtime.compare_bound_file(binding, ref)
    assert same.status == "same"
    assert same.current_file_sha256 == binding.file_sha256
    assert same.current_file_ref is not None
    events = [
        json.loads(line)
        for line in (data_root / "runs" / "run-1" / "events.journal.jsonl").read_text().splitlines()
    ]
    state_check = events[-1]
    assert state_check["kind"] == "state_check"
    assert same.checked_seq == state_check["available_seq"] == state_check["event_seq"]

    path.write_text("def add(a, b):\n    return a - b\n")
    changed = runtime.compare_bound_file(binding, ref)
    assert changed.status == "changed"
    assert changed.current_file_sha256 != binding.file_sha256


def test_compare_file_removal_invalid_utf8_and_symlink_are_unknown(tmp_path: Path) -> None:
    runtime, _, path, binding, ref = _bound_file(tmp_path)
    path.unlink()
    removed = runtime.compare_bound_file(binding, ref)
    assert removed.status == "unknown"

    path.write_bytes(b"\xff")
    invalid = runtime.compare_bound_file(binding, ref)
    assert invalid.status == "unknown"

    path.unlink()
    outside = tmp_path / "outside.py"
    outside.write_text("private")
    path.symlink_to(outside)
    escaped = runtime.compare_bound_file(binding, ref)
    assert escaped.status == "unknown"


def test_compare_file_path_escape_is_unknown_not_guessed(tmp_path: Path) -> None:
    runtime, _, _, binding, ref = _bound_file(tmp_path)
    escaped_binding = binding.model_copy(update={"repo_relative_path": "../outside.py"})
    comparison = runtime.compare_bound_file(escaped_binding, ref)
    assert comparison.status == "unknown"


def test_state_check_sequence_cannot_be_backdated_after_a_later_event(tmp_path: Path) -> None:
    runtime, _, _, binding, ref = _bound_file(tmp_path)
    _, later_seq = runtime.record_event("manager_span", None, {"phase": "later"}, True)
    comparison = runtime.compare_bound_file(binding, ref)
    assert comparison.checked_seq == later_seq + 1
