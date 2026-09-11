"""Offline checks for the disposable F0.5 probe's privacy boundary."""

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

PROBE_PATH = Path("tools/f0_5_probe/reality_probe.py")
SPEC = importlib.util.spec_from_file_location("f0_5_reality_probe", PROBE_PATH)
assert SPEC is not None and SPEC.loader is not None
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)
sanitize_tool_input = PROBE.sanitize_tool_input
sanitized_hook_record = PROBE.sanitized_hook_record
capture_state = PROBE.capture_state
restore_manifest = PROBE.restore_manifest
set_executable_state = PROBE.set_executable_state
EVIDENCE_ROOT = Path("docs/receipts/f0_5_reality_spike")
CLOSURE_EVIDENCE_ROOT = Path("docs/receipts/f0_5_conditional_closure")


def test_hook_sanitizer_excludes_content_and_raw_response() -> None:
    project_root = Path("/tmp/f0-5-demo")
    payload = {
        "cwd": str(project_root),
        "hook_event_name": "PostToolUse",
        "session_id": "session-1",
        "tool_input": {
            "file_path": str(project_root / "calculator.py"),
            "old_string": "sensitive old content",
            "new_string": "sensitive new content",
        },
        "tool_name": "Edit",
        "tool_response": {"content": "sensitive response"},
        "tool_use_id": "tool-1",
        "transcript_path": "/private/transcript.jsonl",
    }

    record = sanitized_hook_record(payload, project_root, "pytest -q")
    serialized = str(record)

    assert record["tool_input"]["file_path"] == "calculator.py"
    assert record["tool_input"]["content_fields_excluded"] == [
        "new_string",
        "old_string",
    ]
    assert "tool_response" in record["excluded_payload_fields"]
    assert "transcript_path" in record["excluded_payload_fields"]
    assert "sensitive" not in serialized
    assert "/private" not in serialized


def test_only_exact_configured_verifier_command_is_persisted() -> None:
    project_root = Path("/tmp/f0-5-demo")

    exact = sanitize_tool_input(
        "Bash",
        {"command": "pytest -q"},
        project_root,
        "pytest -q",
    )
    compound = sanitize_tool_input(
        "Bash",
        {"command": "sed -i s/a/b/ calculator.py && pytest -q"},
        project_root,
        "pytest -q",
    )

    assert exact["command_class"] == "exact_configured_verifier"
    assert exact["command"] == "pytest -q"
    assert exact["run_in_background"] is None
    assert compound["command_class"] == "other_not_persisted"
    assert "command" not in compound


@pytest.mark.parametrize("evidence_root", [EVIDENCE_ROOT, CLOSURE_EVIDENCE_ROOT])
def test_recorded_verdict_evidence_references_match_bytes(
    evidence_root: Path,
) -> None:
    verdict = json.loads((evidence_root / "verdict.json").read_text())
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

    assert references
    for reference in references:
        artifact = evidence_root / reference["path"]
        assert artifact.is_file()
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == reference["sha256"]


def test_integrated_closure_receipt_binds_same_incident_restore() -> None:
    receipt_path = (
        CLOSURE_EVIDENCE_ROOT
        / "integrated/integrated-closure/1789039788376971592-d54a404aeeb5441f8707e818ff143660.json"
    )
    receipt = json.loads(receipt_path.read_text())

    assert receipt["result"] == "pass"
    assert receipt["same_session"] is True
    assert receipt["git_base_matches"] is True
    assert receipt["captured_paths_match"] is True
    assert receipt["mutation_observed_between_results"] is True
    assert receipt["verifier_results"] == {
        "fail_exit_status": 1,
        "pass_exit_status": 0,
    }
    assert receipt["before_restore_manifest_hash"] == receipt["failing_manifest_hash"]
    assert receipt["restore_target_manifest_hash"] == receipt["passing_manifest_hash"]
    assert receipt["restored_manifest_hash"] == receipt["passing_manifest_hash"]

    for reference in receipt["evidence"].values():
        artifact = CLOSURE_EVIDENCE_ROOT / "integrated" / reference["path"]
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == reference["sha256"]


@pytest.mark.parametrize("evidence_root", [EVIDENCE_ROOT, CLOSURE_EVIDENCE_ROOT])
def test_persisted_hook_records_do_not_contain_disallowed_raw_values(
    evidence_root: Path,
) -> None:
    invocation_files = sorted(evidence_root.glob("**/invocations/*.json"))

    assert invocation_files
    for artifact in invocation_files:
        record = json.loads(artifact.read_text())
        serialized = json.dumps(record, sort_keys=True)
        assert "/home/" not in serialized
        assert "/tmp/" not in serialized
        assert "ghp_" not in serialized
        assert "sk-ant-" not in serialized


def test_executable_state_round_trips_for_tracked_and_selected_untracked(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    evidence = tmp_path / "evidence"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "probe@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "F0.5 Probe"],
        check=True,
    )
    non_executable = repo / "plain.txt"
    executable = repo / "run.sh"
    selected = repo / "selected.sh"
    non_executable.write_text("plain\n")
    executable.write_text("#!/bin/sh\nexit 0\n")
    selected.write_text("#!/bin/sh\nexit 0\n")
    set_executable_state(executable, True)
    set_executable_state(selected, True)
    subprocess.run(
        ["git", "-C", str(repo), "add", "plain.txt", "run.sh"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "fixture"],
        check=True,
    )

    baseline = capture_state(repo, evidence, ["selected.sh"])
    mutations = [
        (non_executable, True),
        (executable, False),
        (selected, False),
    ]
    for path, mutated_state in mutations:
        set_executable_state(path, mutated_state)
        mutated = capture_state(repo, evidence, ["selected.sh"])
        assert mutated["manifest_hash"] != baseline["manifest_hash"]
        restore_manifest(repo, evidence, baseline["manifest_hash"])
        restored = capture_state(repo, evidence, ["selected.sh"])
        assert restored["manifest_hash"] == baseline["manifest_hash"]

    assert PROBE.executable_state(non_executable) is False
    assert PROBE.executable_state(executable) is True
    assert PROBE.executable_state(selected) is True
