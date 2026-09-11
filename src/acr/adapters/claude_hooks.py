"""Claude Code hook translation into privacy-bounded stable observations."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_HOOK_EVENTS = {
    "SessionStart",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "SessionEnd",
}
TOOL_HOOK_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure"}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sanitized_repo_path(value: object, repo_root: Path) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        return "unknown"
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    normalized = Path(os.path.abspath(candidate))
    try:
        relative = normalized.relative_to(repo_root)
    except ValueError:
        return "outside_repository"
    return "." if relative == Path(".") else relative.as_posix()


def is_exact_verifier_invocation(payload: dict[str, Any], verifier: str) -> bool:
    tool_input = payload.get("tool_input")
    return (
        payload.get("tool_name") == "Bash"
        and isinstance(tool_input, dict)
        and tool_input.get("command") == verifier
        and tool_input.get("run_in_background") is not True
    )


def sanitize_claude_hook_payload(
    payload: dict[str, Any],
    repo_root: Path,
    verifier: str,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Drop prompt, response, error, environment, and transcript content."""

    event_name = payload.get("hook_event_name")
    session_id = payload.get("session_id")
    if not isinstance(event_name, str) or event_name not in SUPPORTED_HOOK_EVENTS:
        raise ValueError("unsupported Claude hook event")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Claude hook event has no session identity")

    safe: dict[str, Any] = {
        "cwd_scope": _sanitized_repo_path(payload.get("cwd"), repo_root),
        "external_session_hash": _sha256_text(session_id),
        "hook_event_name": event_name,
        "observed_at": (observed_at or datetime.now(timezone.utc)).isoformat(),
        "privacy": {
            "environment_values_persisted": False,
            "prompt_body_persisted": False,
            "raw_payload_persisted": False,
            "tool_response_body_persisted": False,
            "transcript_path_persisted": False,
        },
        "schema": "acr.claude-hook-observation/0.1",
    }
    if event_name in TOOL_HOOK_EVENTS:
        tool_name = payload.get("tool_name")
        operation_id = payload.get("tool_use_id")
        safe["operation"] = {
            "name": tool_name if isinstance(tool_name, str) and tool_name else "unknown",
            "occurrence_id": (
                operation_id
                if isinstance(operation_id, str) and operation_id
                else "unknown"
            ),
        }
        tool_input = payload.get("tool_input")
        summary: dict[str, Any]
        if tool_name == "Bash" and isinstance(tool_input, dict):
            exact = is_exact_verifier_invocation(payload, verifier)
            summary = {
                "command": verifier if exact else None,
                "command_class": (
                    "exact_configured_verifier" if exact else "other_not_persisted"
                ),
                "run_in_background": (
                    tool_input.get("run_in_background") if exact else None
                ),
            }
        elif tool_name in {"Read", "Edit", "Write"} and isinstance(tool_input, dict):
            summary = {
                "content_fields_excluded": sorted(
                    key
                    for key in ("content", "old_string", "new_string")
                    if key in tool_input
                ),
                "file_path": _sanitized_repo_path(tool_input.get("file_path"), repo_root),
            }
        else:
            summary = {"payload_fields_persisted": False}
        safe["tool_input_summary"] = summary
        safe["duration_ms"] = (
            payload.get("duration_ms")
            if isinstance(payload.get("duration_ms"), int)
            and payload.get("duration_ms") >= 0
            else None
        )
        safe["is_interrupt"] = payload.get("is_interrupt") is True
        safe["error_body_persisted"] = False
    elif event_name == "SessionStart":
        source = payload.get("source")
        safe["source"] = source if source in {"startup", "resume", "clear", "compact"} else "unknown"
    elif event_name == "SessionEnd":
        reason = payload.get("reason")
        safe["reason"] = reason if isinstance(reason, str) and len(reason) <= 64 else "unknown"
    return safe
