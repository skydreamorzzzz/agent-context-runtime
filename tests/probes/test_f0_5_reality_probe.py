"""Offline checks for the disposable F0.5 probe's privacy boundary."""

import hashlib
import importlib.util
import json
from pathlib import Path

PROBE_PATH = Path("tools/f0_5_probe/reality_probe.py")
SPEC = importlib.util.spec_from_file_location("f0_5_reality_probe", PROBE_PATH)
assert SPEC is not None and SPEC.loader is not None
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)
sanitize_tool_input = PROBE.sanitize_tool_input
sanitized_hook_record = PROBE.sanitized_hook_record
EVIDENCE_ROOT = Path("docs/receipts/f0_5_reality_spike")


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


def test_recorded_verdict_evidence_references_match_bytes() -> None:
    verdict = json.loads((EVIDENCE_ROOT / "verdict.json").read_text())
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
        artifact = EVIDENCE_ROOT / reference["path"]
        assert artifact.is_file()
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == reference["sha256"]


def test_persisted_hook_records_do_not_contain_disallowed_raw_values() -> None:
    invocation_files = sorted(EVIDENCE_ROOT.glob("*/invocations/*.json"))

    assert invocation_files
    for artifact in invocation_files:
        record = json.loads(artifact.read_text())
        serialized = json.dumps(record, sort_keys=True)
        assert "/home/" not in serialized
        assert "/tmp/" not in serialized
        assert "ghp_" not in serialized
        assert "sk-ant-" not in serialized
