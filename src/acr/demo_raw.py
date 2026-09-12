"""Explicitly opted-in, local-only Claude trajectory capture for the static demo."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCE_CLASS = "demo_raw"
RAW_SCHEMA = "acr.demo-raw-session/0.1"
STEP_SCHEMA = "acr.demo-raw-steps/0.1"
HIT_SCHEMA = "acr.demo-diagnostic-hits/0.1"
_EXIT_CODE_LINE = re.compile(r"Exit code ([0-9]+)")


class DemoRawCaptureError(RuntimeError):
    """The explicitly requested local raw capture could not be materialized."""


def demo_raw_session_path(repo_root: Path, session_id: str, *, enabled: bool) -> Path | None:
    """Return the local raw session path only when the user opted in."""

    return repo_root / ".acr" / "demo-raw" / session_id if enabled else None


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def initialize_demo_raw_session(
    session_dir: Path,
    *,
    acr_session_id: str,
    claude_version: str,
    repo_root: Path,
    verifier: str,
) -> None:
    """Create local-only metadata without changing the F1 evidence store."""

    session_dir.mkdir(parents=True, exist_ok=False)
    session_dir.chmod(0o700)
    _atomic_json(
        session_dir / "metadata.json",
        {
            "acr_session_id": acr_session_id,
            "claude_version": claude_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "repository": str(repo_root),
            "schema": RAW_SCHEMA,
            "source_class": SOURCE_CLASS,
            "verifier": verifier,
        },
    )


def observe_demo_raw_hook(raw_input: bytes, session_dir: Path) -> None:
    """Remember Claude's own transcript and refresh a local materialized snapshot."""

    try:
        payload = json.loads(raw_input)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise DemoRawCaptureError("Claude hook payload is not valid JSON") from error
    if not isinstance(payload, dict):
        raise DemoRawCaptureError("Claude hook payload is not an object")
    transcript_path = payload.get("transcript_path")
    raw_session_id = payload.get("session_id")
    if not isinstance(transcript_path, str) or not transcript_path:
        raise DemoRawCaptureError("Claude hook payload has no transcript_path")
    if not isinstance(raw_session_id, str) or not raw_session_id:
        raise DemoRawCaptureError("Claude hook payload has no session_id")
    metadata_path = session_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.update(
        {
            "last_hook_event": payload.get("hook_event_name"),
            "raw_session_id": raw_session_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if payload.get("hook_event_name") == "SessionEnd":
        metadata["ended_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(metadata_path, metadata)
    _atomic_json(
        session_dir / "source-binding.json",
        {
            "raw_session_id": raw_session_id,
            "source_class": SOURCE_CLASS,
            "transcript_path": transcript_path,
        },
    )
    finalize_demo_raw_session(session_dir)


def _text_content(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
            else:
                parts.append(json.dumps(item, sort_keys=True))
        return "\n".join(parts)
    return json.dumps(value, sort_keys=True)


def _usage(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, int) and not isinstance(item, bool)
    }


def normalize_claude_jsonl(source: bytes) -> list[dict[str, Any]]:
    """Normalize the observed Claude 2.1.144 JSONL message/tool shape."""

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise DemoRawCaptureError(f"malformed Claude JSONL at line {line_number}") from error
        if isinstance(value, dict):
            records.append(value)

    steps: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}

    def append_step(step: dict[str, Any]) -> dict[str, Any]:
        step.update(
            {
                "schema": STEP_SCHEMA,
                "sequence": len(steps) + 1,
                "source_class": SOURCE_CLASS,
            }
        )
        steps.append(step)
        return step

    for source_position, record in enumerate(records, start=1):
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        timestamp = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
        common = {"source_position": source_position, "timestamp": timestamp}
        if role == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    append_step(
                        {
                            **common,
                            "body": block["text"],
                            "body_bytes": len(block["text"].encode()),
                            "body_chars": len(block["text"]),
                            "kind": "assistant",
                            "usage": _usage(message.get("usage")),
                        }
                    )
                elif block.get("type") == "tool_use":
                    occurrence_id = block.get("id")
                    tool = block.get("name")
                    tool_input = block.get("input")
                    if not isinstance(occurrence_id, str) or occurrence_id in tools:
                        continue
                    step = append_step(
                        {
                            **common,
                            "exit_code": None,
                            "input": tool_input if isinstance(tool_input, dict) else {},
                            "kind": "tool",
                            "occurrence_id": occurrence_id,
                            "output": None,
                            "output_bytes": None,
                            "success": None,
                            "tool": tool if isinstance(tool, str) else "unknown",
                            "usage": _usage(message.get("usage")),
                        }
                    )
                    tools[occurrence_id] = step
        elif role == "user" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                occurrence_id = block.get("tool_use_id")
                if not isinstance(occurrence_id, str) or occurrence_id not in tools:
                    continue
                output = _text_content(block.get("content"))
                first_line = output.splitlines()[0] if output else ""
                exit_match = _EXIT_CODE_LINE.fullmatch(first_line)
                tools[occurrence_id].update(
                    {
                        "exit_code": int(exit_match.group(1)) if exit_match else None,
                        "output": output,
                        "output_bytes": len(output.encode()),
                        "success": block.get("is_error") is not True,
                    }
                )
        elif role == "user" and isinstance(content, str):
            append_step(
                {
                    **common,
                    "body": content,
                    "body_bytes": len(content.encode()),
                    "body_chars": len(content),
                    "kind": "user",
                    "usage": {},
                }
            )
    return steps


def _normalized_command(command: str) -> str:
    return command.replace("\r\n", "\n").rstrip("\n")


def detect_demo_diagnostics(
    steps: list[dict[str, Any]], *, verifier: str, source_hash: str
) -> list[dict[str, Any]]:
    """Emit two exact, demo-only signals; neither claims full W04/W06 semantics."""

    hits: list[dict[str, Any]] = []
    prior_reads: dict[tuple[str, str], dict[str, Any]] = {}
    prior_commands: dict[str, dict[str, Any]] = {}
    for step in steps:
        if step.get("kind") != "tool" or step.get("success") is not True:
            continue
        tool_input = step.get("input")
        if not isinstance(tool_input, dict):
            continue
        if step.get("tool") == "Read":
            path = tool_input.get("file_path")
            output = step.get("output")
            complete_request = "offset" not in tool_input and "limit" not in tool_input
            if not isinstance(path, str) or not isinstance(output, str) or not complete_request:
                continue
            output_hash = hashlib.sha256(output.encode()).hexdigest()
            key = (path, output_hash)
            earlier = prior_reads.get(key)
            if earlier is not None:
                hits.append(
                    _hit(
                        diagnostic_id="exact_repeated_read_result_v1",
                        rule_family="W04-compatible",
                        step=step,
                        earlier=earlier,
                        source_hash=source_hash,
                        summary="相同路径的完整 Read 请求返回了完全相同的记录内容",
                    )
                )
            prior_reads[key] = step
        elif step.get("tool") == "Bash":
            command = tool_input.get("command")
            if not isinstance(command, str):
                continue
            normalized = _normalized_command(command)
            if normalized == verifier:
                continue
            earlier = prior_commands.get(normalized)
            if earlier is not None:
                hits.append(
                    _hit(
                        diagnostic_id="exact_repeated_command_v1",
                        rule_family="W06-compatible",
                        step=step,
                        earlier=earlier,
                        source_hash=source_hash,
                        summary="同一受控会话中出现完全相同的 Bash command",
                    )
                )
            prior_commands[normalized] = step
    return hits


def _hit(
    *,
    diagnostic_id: str,
    rule_family: str,
    step: dict[str, Any],
    earlier: dict[str, Any],
    source_hash: str,
    summary: str,
) -> dict[str, Any]:
    return {
        "detector_version": diagnostic_id,
        "diagnostic_id": diagnostic_id,
        "event_sequence": step["sequence"],
        "occurrence_id": step.get("occurrence_id"),
        "related_occurrence_ids": [earlier.get("occurrence_id")],
        "related_sequences": [earlier["sequence"]],
        "rule_family": rule_family,
        "schema": HIT_SCHEMA,
        "severity": "yellow",
        "source_class": SOURCE_CLASS,
        "source_hash": source_hash,
        "summary": summary,
        "tool": step.get("tool"),
    }


def finalize_demo_raw_session(session_dir: Path) -> None:
    """Copy Claude's local JSONL and derive normalized steps plus diagnostic hits."""

    binding_path = session_dir / "source-binding.json"
    if not binding_path.is_file():
        return
    binding = json.loads(binding_path.read_text())
    transcript = Path(binding["transcript_path"])
    if not transcript.is_file():
        return
    source_dir = session_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    destination = source_dir / "claude-transcript.jsonl"
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    shutil.copyfile(transcript, temporary)
    os.replace(temporary, destination)
    source = destination.read_bytes()
    source_hash = hashlib.sha256(source).hexdigest()
    metadata = json.loads((session_dir / "metadata.json").read_text())
    steps = normalize_claude_jsonl(source)
    hits = detect_demo_diagnostics(
        steps,
        verifier=metadata["verifier"],
        source_hash=source_hash,
    )
    _atomic_json(session_dir / "normalized" / "steps.json", {"steps": steps})
    _atomic_json(session_dir / "diagnostics" / "hits.json", {"hits": hits})
    metadata.update(
        {
            "diagnostic_hit_count": len(hits),
            "normalized_step_count": len(steps),
            "source_hash": source_hash,
        }
    )
    _atomic_json(session_dir / "metadata.json", metadata)
