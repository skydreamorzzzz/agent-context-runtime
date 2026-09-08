"""Current file verification against an exact historical read binding."""

from __future__ import annotations

import hashlib
from pathlib import Path

from acr.contracts import FileBinding, InformationLabel
from acr.state import compare_file
from acr.store import ingest_runtime_bytes


def _bound_file(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "target.py"
    raw = b"def add(a, b):\n    pass\n"
    path.write_bytes(raw)
    data_root = tmp_path / "data"
    ref = ingest_runtime_bytes(raw, data_root, "run-1", "/tools/tool:run-1:0/body")
    ref = ref.model_copy(
        update={
            "labels": [InformationLabel(scope="runtime", run_id="run-1", available_seq=2)]
        }
    )
    binding = FileBinding(
        repo_relative_path="target.py",
        file_sha256=hashlib.sha256(raw).hexdigest(),
        encoding="utf-8",
        read_event_id="event:run-1:2",
        observed_seq=2,
        complete=True,
    )
    return workspace, data_root, path, binding, ref


def test_compare_file_reports_same_then_changed_from_current_bytes(tmp_path: Path) -> None:
    workspace, data_root, path, binding, ref = _bound_file(tmp_path)
    same = compare_file(
        workspace, binding, ref, data_root=data_root, run_id="run-1", checked_seq=3
    )
    assert same.status == "same"
    assert same.current_file_sha256 == binding.file_sha256
    assert same.current_file_ref is not None

    path.write_text("def add(a, b):\n    return a - b\n")
    changed = compare_file(
        workspace, binding, ref, data_root=data_root, run_id="run-1", checked_seq=4
    )
    assert changed.status == "changed"
    assert changed.current_file_sha256 != binding.file_sha256


def test_compare_file_removal_invalid_utf8_and_symlink_are_unknown(tmp_path: Path) -> None:
    workspace, data_root, path, binding, ref = _bound_file(tmp_path)
    path.unlink()
    removed = compare_file(
        workspace, binding, ref, data_root=data_root, run_id="run-1", checked_seq=3
    )
    assert removed.status == "unknown"

    path.write_bytes(b"\xff")
    invalid = compare_file(
        workspace, binding, ref, data_root=data_root, run_id="run-1", checked_seq=4
    )
    assert invalid.status == "unknown"

    path.unlink()
    outside = tmp_path / "outside.py"
    outside.write_text("private")
    path.symlink_to(outside)
    escaped = compare_file(
        workspace, binding, ref, data_root=data_root, run_id="run-1", checked_seq=5
    )
    assert escaped.status == "unknown"


def test_compare_file_path_escape_is_unknown_not_guessed(tmp_path: Path) -> None:
    workspace, data_root, _, binding, ref = _bound_file(tmp_path)
    escaped_binding = binding.model_copy(update={"repo_relative_path": "../outside.py"})
    comparison = compare_file(
        workspace,
        escaped_binding,
        ref,
        data_root=data_root,
        run_id="run-1",
        checked_seq=3,
    )
    assert comparison.status == "unknown"
