"""Demo-only raw trajectory capture and exact diagnostic tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from acr.demo_raw import (
    demo_raw_session_path,
    detect_demo_diagnostics,
    initialize_demo_raw_session,
    normalize_claude_jsonl,
    observe_demo_raw_hook,
)


def _jsonl(records: list[dict[str, object]]) -> bytes:
    return b"".join(json.dumps(item).encode() + b"\n" for item in records)


def _tool_use(occurrence_id: str, name: str, tool_input: dict[str, object]) -> dict[str, object]:
    return {
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": occurrence_id, "name": name, "input": tool_input}
            ],
            "usage": {"input_tokens": 12, "output_tokens": 3},
        },
        "timestamp": "2026-09-12T00:00:00Z",
        "type": "assistant",
    }


def _tool_result(occurrence_id: str, output: str) -> dict[str, object]:
    return {
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": occurrence_id,
                    "content": output,
                    "is_error": False,
                }
            ],
        },
        "timestamp": "2026-09-12T00:00:01Z",
        "type": "user",
    }


def test_raw_mode_is_off_by_default_and_directory_is_ignored(tmp_path: Path) -> None:
    assert demo_raw_session_path(tmp_path, "session-1", enabled=False) is None
    assert demo_raw_session_path(tmp_path, "session-1", enabled=True) == (
        tmp_path / ".acr" / "demo-raw" / "session-1"
    )
    result = subprocess.run(
        ["git", "check-ignore", ".acr/demo-raw/private.jsonl"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_opt_in_materializes_ordered_raw_steps_and_diagnostics(tmp_path: Path) -> None:
    source = _jsonl(
        [
            {"message": {"role": "user", "content": "Inspect twice"}, "type": "user"},
            _tool_use("read-1", "Read", {"file_path": "/repo/a.py"}),
            _tool_result("read-1", "1: value = 1"),
            _tool_use("read-2", "Read", {"file_path": "/repo/a.py"}),
            _tool_result("read-2", "1: value = 1"),
            _tool_use("bash-1", "Bash", {"command": "git status --short"}),
            _tool_result("bash-1", ""),
            _tool_use("bash-2", "Bash", {"command": "git status --short"}),
            _tool_result("bash-2", ""),
            _tool_use("verify-1", "Bash", {"command": "pytest -q"}),
            _tool_result("verify-1", "passed"),
            _tool_use("verify-2", "Bash", {"command": "pytest -q"}),
            _tool_result("verify-2", "passed"),
        ]
    )
    transcript = tmp_path / "claude.jsonl"
    transcript.write_bytes(source)
    session_dir = tmp_path / ".acr" / "demo-raw" / "session-test"
    initialize_demo_raw_session(
        session_dir,
        acr_session_id="session-test",
        claude_version="2.1.144 (Claude Code)",
        repo_root=tmp_path,
        verifier="pytest -q",
    )
    observe_demo_raw_hook(
        json.dumps(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "claude-session",
                "transcript_path": str(transcript),
            }
        ).encode(),
        session_dir,
    )

    steps = json.loads((session_dir / "normalized" / "steps.json").read_text())["steps"]
    hits = json.loads((session_dir / "diagnostics" / "hits.json").read_text())["hits"]
    assert [step["sequence"] for step in steps] == list(range(1, len(steps) + 1))
    assert (session_dir / "source" / "claude-transcript.jsonl").read_bytes() == source
    assert {hit["diagnostic_id"] for hit in hits} == {
        "exact_repeated_read_result_v1",
        "exact_repeated_command_v1",
    }
    assert all(hit["severity"] == "yellow" for hit in hits)
    assert all(hit["source_class"] == "demo_raw" for hit in hits)
    assert all(isinstance(hit["event_sequence"], int) for hit in hits)
    assert all(hit["related_sequences"] for hit in hits)
    assert all(hit["source_hash"] == hashlib.sha256(source).hexdigest() for hit in hits)
    assert sum(hit["diagnostic_id"] == "exact_repeated_command_v1" for hit in hits) == 1


def test_partial_read_is_not_promoted_to_exact_repeated_read() -> None:
    source = _jsonl(
        [
            _tool_use("read-1", "Read", {"file_path": "/repo/a.py", "limit": 10}),
            _tool_result("read-1", "same"),
            _tool_use("read-2", "Read", {"file_path": "/repo/a.py", "limit": 10}),
            _tool_result("read-2", "same"),
        ]
    )
    steps = normalize_claude_jsonl(source)
    assert detect_demo_diagnostics(steps, verifier="pytest -q", source_hash="a" * 64) == []
