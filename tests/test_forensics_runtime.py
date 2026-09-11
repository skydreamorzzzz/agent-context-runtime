"""F1 production capture, privacy, checkpoint, and verifier-binding tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from acr.adapters.claude_hooks import (
    is_exact_verifier_invocation,
    sanitize_claude_hook_payload,
)
from acr.contracts import EvidenceRef, InformationLabel
from acr.forensics.config import ForensicsConfig
from acr.forensics.session import audit_session, build_claude_settings, handle_claude_hook
from acr.forensics.store import ForensicsEvidenceStore
from acr.forensics_contracts import (
    AgentEvent,
    CapturedPathState,
    VerificationReceipt,
    WorkspaceCheckpoint,
    canonical_captured_state_manifest_bytes,
)

GOLDEN_MANIFEST = Path(
    "docs/receipts/f0_5_conditional_closure/integrated/manifests/"
    "77cd2dd93f01a0158711bae3eea3ed62c15084829f96edb7dd885dfbce80f47c.json"
)
F1_SMOKE_EVIDENCE = Path("docs/receipts/f1_product_core")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "f1@example.invalid")
    _git(repo, "config", "user.name", "F1 Test")
    (repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "test_calculator.py").write_text(
        "from calculator import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    executable = repo / "run.sh"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    (repo / ".env").write_text("ACR_PRIVATE_SENTINEL=must-never-persist\n")
    (repo / "accidental.txt").write_text("ghp_NEVER_PERSIST_THIS_VALUE\n")
    (repo / ".gitignore").write_text("ignored.txt\n")
    _git(
        repo,
        "add",
        ".gitignore",
        ".env",
        "accidental.txt",
        "calculator.py",
        "run.sh",
        "test_calculator.py",
    )
    _git(repo, "commit", "-q", "-m", "fixture")
    selected = repo / "selected.sh"
    selected.write_text("#!/bin/sh\nexit 0\n")
    selected.chmod(0o755)
    return repo


def _initialize(data_root: Path, repo: Path, session_id: str = "session-test") -> None:
    ForensicsEvidenceStore(data_root, session_id).initialize_session(
        repo_identity_hash=hashlib.sha256(str(repo.resolve()).encode()).hexdigest(),
        verifier="pytest -q",
        selected_untracked_paths=["selected.sh"],
        max_blob_bytes=1024 * 1024,
        claude_version="2.1.144 (Claude Code)",
    )


def _payload(event: str, repo: Path, operation: str, command: str = "pytest -q") -> bytes:
    value: dict[str, object] = {
        "cwd": str(repo),
        "hook_event_name": event,
        "session_id": "real-claude-session",
        "tool_input": {"command": command},
        "tool_name": "Bash",
        "tool_use_id": operation,
        "transcript_path": "/private/transcript.jsonl",
    }
    if event == "PostToolUse":
        value["tool_response"] = {"stdout": "PRIVATE_TOOL_RESPONSE"}
    elif event == "PostToolUseFailure":
        value["error"] = "PRIVATE_FAILURE_BODY"
        value["is_interrupt"] = False
    return json.dumps(value).encode()


def _records(store: ForensicsEvidenceStore, category: str, model: type):
    return [model.model_validate_json(path.read_text()) for path in store.record_files(category)]


def test_claude_adapter_sanitizes_content_and_only_promotes_exact_verifier(
    tmp_path: Path,
) -> None:
    repo = tmp_path.resolve()
    payload = {
        "cwd": str(repo),
        "hook_event_name": "PostToolUse",
        "session_id": "claude-session",
        "tool_input": {
            "file_path": str(repo / "calculator.py"),
            "new_string": "PRIVATE_NEW_CONTENT",
            "old_string": "PRIVATE_OLD_CONTENT",
        },
        "tool_name": "Edit",
        "tool_response": {"content": "PRIVATE_RESPONSE"},
        "tool_use_id": "tool-1",
        "transcript_path": "/private/transcript.jsonl",
    }
    safe = sanitize_claude_hook_payload(payload, repo, "pytest -q")
    serialized = json.dumps(safe)

    assert safe["tool_input_summary"] == {
        "content_fields_excluded": ["new_string", "old_string"],
        "file_path": "calculator.py",
    }
    assert "PRIVATE" not in serialized
    assert "/private/transcript.jsonl" not in serialized
    assert "claude-session" not in serialized

    exact = json.loads(_payload("PreToolUse", repo, "tool-2"))
    compound = json.loads(
        _payload("PreToolUse", repo, "tool-3", "sed -i s/a/b/ x.py && pytest -q")
    )
    background = json.loads(_payload("PreToolUse", repo, "tool-4"))
    background["tool_input"]["run_in_background"] = True
    assert is_exact_verifier_invocation(exact, "pytest -q") is True
    assert is_exact_verifier_invocation(compound, "pytest -q") is False
    assert is_exact_verifier_invocation(background, "pytest -q") is False
    compound_safe = sanitize_claude_hook_payload(compound, repo, "pytest -q")
    assert compound_safe["tool_input_summary"]["command"] is None


def test_config_rejects_compound_verifier_and_path_traversal() -> None:
    with pytest.raises(ValidationError, match="standalone command"):
        ForensicsConfig(verifier="sed -i s/a/b/ x.py && pytest -q")
    with pytest.raises(ValidationError, match="repository-relative"):
        ForensicsConfig(verifier="pytest -q", selected_untracked_paths=["../outside"])


def test_temporary_settings_register_product_hooks_without_replacing_settings() -> None:
    settings = build_claude_settings("python -m acr.cli _forensics-hook")

    assert set(settings) == {"hooks"}
    assert set(settings["hooks"]) == {
        "PostToolUse",
        "PostToolUseFailure",
        "PreToolUse",
        "SessionEnd",
        "SessionStart",
    }
    assert settings["hooks"]["PreToolUse"][0]["matcher"] == "*"


def test_production_capture_binds_pass_and_fail_to_distinct_real_states(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    data_root = tmp_path / "evidence"
    _initialize(data_root, repo)

    assert handle_claude_hook(
        raw_input=_payload("PreToolUse", repo, "tool-pass"),
        data_root=data_root,
        session_id="session-test",
        repo_root=repo,
    ) == 0
    assert handle_claude_hook(
        raw_input=_payload("PostToolUse", repo, "tool-pass"),
        data_root=data_root,
        session_id="session-test",
        repo_root=repo,
    ) == 0
    (repo / "calculator.py").write_text("def add(a, b):\n    return a - b\n")
    (repo / "run.sh").unlink()
    assert handle_claude_hook(
        raw_input=_payload("PreToolUse", repo, "tool-fail"),
        data_root=data_root,
        session_id="session-test",
        repo_root=repo,
    ) == 0
    assert handle_claude_hook(
        raw_input=_payload("PostToolUseFailure", repo, "tool-fail"),
        data_root=data_root,
        session_id="session-test",
        repo_root=repo,
    ) == 0

    store = ForensicsEvidenceStore(data_root, "session-test")
    checkpoints = _records(store, "checkpoints", WorkspaceCheckpoint)
    receipts = _records(store, "receipts", VerificationReceipt)
    events = _records(store, "events", AgentEvent)
    checkpoints.sort(key=lambda item: item.ordering.sequence.value or -1)
    receipts.sort(key=lambda item: item.ordering.sequence.value if item.ordering else -1)
    assert len(checkpoints) == 2
    assert len(receipts) == 2
    assert len(events) == 4
    assert all(item.contract_status == "v0.1_frozen" for item in [*events, *checkpoints, *receipts])
    assert {item.passed.value for item in receipts} == {True, False}
    assert len({item.captured_workspace_manifest_hash for item in checkpoints}) == 2
    by_id = {item.id: item for item in checkpoints}
    for receipt in receipts:
        checkpoint = by_id[receipt.pre_checkpoint_id]
        assert receipt.session_id == checkpoint.session_id == "session-test"
        assert (
            receipt.tested_captured_workspace_manifest_hash
            == checkpoint.captured_workspace_manifest_hash
        )
        assert receipt.operation is not None
        assert receipt.stdout_ref is None and receipt.stderr_ref is None
    assert audit_session(data_root, "session-test") == []

    first = checkpoints[0]
    captured = {item.repo_relative_path: item for item in first.captured_paths}
    assert captured["run.sh"].executable is True
    assert captured["calculator.py"].executable is False
    assert captured["selected.sh"].path_kind == "selected_untracked"
    assert captured["selected.sh"].executable is True
    assert ".env" not in captured
    assert "accidental.txt" not in captured
    assert any(
        item.repo_relative_path == ".env"
        and item.disposition == "excluded_by_policy"
        and item.captured.value is False
        for item in first.capture_scope
    )
    deleted = {item.repo_relative_path: item for item in checkpoints[1].captured_paths}["run.sh"]
    assert deleted.state == "deleted"
    assert deleted.content_ref is None
    assert deleted.executable is None

    persisted = b"\n".join(
        path.read_bytes() for path in data_root.rglob("*") if path.is_file()
    )
    for forbidden in (
        b"must-never-persist",
        b"PRIVATE_TOOL_RESPONSE",
        b"PRIVATE_FAILURE_BODY",
        b"/private/transcript",
        b"ghp_NEVER_PERSIST_THIS_VALUE",
    ):
        assert forbidden not in persisted


def test_compound_or_uncorrelated_verifier_never_emits_receipt(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    data_root = tmp_path / "evidence"
    _initialize(data_root, repo)

    compound = "sed -i s/a/b/ calculator.py && pytest -q"
    for event in ("PreToolUse", "PostToolUse"):
        assert handle_claude_hook(
            raw_input=_payload(event, repo, "compound", compound),
            data_root=data_root,
            session_id="session-test",
            repo_root=repo,
        ) == 0
    assert handle_claude_hook(
        raw_input=_payload("PostToolUse", repo, "no-pre"),
        data_root=data_root,
        session_id="session-test",
        repo_root=repo,
    ) == 0

    store = ForensicsEvidenceStore(data_root, "session-test")
    assert store.record_files("checkpoints") == []
    assert store.record_files("receipts") == []
    assert store.record_files("anomalies")


def test_cross_session_result_cannot_consume_pre_state(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    data_root = tmp_path / "evidence"
    _initialize(data_root, repo)
    assert handle_claude_hook(
        raw_input=_payload("PreToolUse", repo, "cross-session"),
        data_root=data_root,
        session_id="session-test",
        repo_root=repo,
    ) == 0
    post = json.loads(_payload("PostToolUse", repo, "cross-session"))
    post["session_id"] = "different-claude-session"
    assert handle_claude_hook(
        raw_input=json.dumps(post).encode(),
        data_root=data_root,
        session_id="session-test",
        repo_root=repo,
    ) == 0

    store = ForensicsEvidenceStore(data_root, "session-test")
    assert len(store.record_files("checkpoints")) == 1
    assert store.record_files("receipts") == []
    assert store.record_files("anomalies")


def test_session_audit_blocks_receipt_checkpoint_session_mismatch(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    data_root = tmp_path / "evidence"
    _initialize(data_root, repo)
    for event in ("PreToolUse", "PostToolUse"):
        assert handle_claude_hook(
            raw_input=_payload(event, repo, "tamper-target"),
            data_root=data_root,
            session_id="session-test",
            repo_root=repo,
        ) == 0
    store = ForensicsEvidenceStore(data_root, "session-test")
    receipt_path = store.record_files("receipts")[0]
    tampered = json.loads(receipt_path.read_text())
    tampered["session_id"] = "another-session"
    receipt_path.chmod(0o644)
    receipt_path.write_text(json.dumps(tampered))

    issues = audit_session(data_root, "session-test")
    assert any("receipt/checkpoint session mismatch" in issue for issue in issues)


def test_selected_symlink_is_an_explicit_gap_and_outside_bytes_are_not_read(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("OUTSIDE_PRIVATE_SENTINEL")
    (repo / "selected.sh").unlink()
    (repo / "selected.sh").symlink_to(outside)
    data_root = tmp_path / "evidence"
    _initialize(data_root, repo)

    assert handle_claude_hook(
        raw_input=_payload("PreToolUse", repo, "tool-symlink"),
        data_root=data_root,
        session_id="session-test",
        repo_root=repo,
    ) == 0
    store = ForensicsEvidenceStore(data_root, "session-test")
    checkpoint = _records(store, "checkpoints", WorkspaceCheckpoint)[0]
    assert "selected.sh" not in {item.repo_relative_path for item in checkpoint.captured_paths}
    assert any(
        item.repo_relative_path == "selected.sh"
        and item.disposition == "unsupported"
        and item.reason == "symlink_or_non_directory_component"
        for item in checkpoint.capture_scope
    )
    persisted = b"".join(path.read_bytes() for path in data_root.rglob("*") if path.is_file())
    assert b"OUTSIDE_PRIVATE_SENTINEL" not in persisted


def test_f0_5_real_manifest_is_byte_exact_golden_for_production_canonicalizer() -> None:
    manifest_bytes = GOLDEN_MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)
    dummy = EvidenceRef(
        blob_hash="0" * 64,
        source_id="golden",
        trajectory_key="f0.5",
        locator="/manifest",
        labels=[InformationLabel(scope="analysis")],
    )
    paths = [
        CapturedPathState(
            repo_relative_path=item["path"],
            path_kind=item["path_kind"],
            state=item["state"],
            state_ref=dummy,
            content_ref=(
                dummy.model_copy(update={"blob_hash": item["content_hash"]})
                if item["content_hash"] is not None
                else None
            ),
            executable=item["executable"],
        )
        for item in manifest["paths"]
    ]
    production_bytes = canonical_captured_state_manifest_bytes(manifest["git_base"], paths)

    assert production_bytes == manifest_bytes
    assert hashlib.sha256(production_bytes).hexdigest() == GOLDEN_MANIFEST.stem


def test_committed_f1_smoke_references_and_privacy_boundary() -> None:
    verdict = json.loads((F1_SMOKE_EVIDENCE / "verdict.json").read_text())
    references: list[dict[str, str]] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            if set(value) == {"path", "sha256"}:
                references.append(value)
            else:
                for nested in value.values():
                    collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    collect(verdict)
    assert verdict["result"] == "PASS"
    assert verdict["observations"]["results_in_observed_order"] == ["PASS", "FAIL"]
    assert len(references) == 6
    for reference in references:
        artifact = F1_SMOKE_EVIDENCE / reference["path"]
        assert artifact.is_file()
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == reference["sha256"]

    persisted = b"\n".join(
        path.read_bytes() for path in F1_SMOKE_EVIDENCE.rglob("*") if path.is_file()
    )
    for forbidden in (
        b"/home/",
        b"/tmp/",
        b"Follow these steps exactly",
        b"ghp_",
        b"sk-ant-",
        b"-----BEGIN PRIVATE KEY-----",
    ):
        assert forbidden not in persisted
