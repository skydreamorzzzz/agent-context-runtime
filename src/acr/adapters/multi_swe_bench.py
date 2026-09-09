"""Thin adapter for the pinned Multi-SWE-bench Flash OpenHands event format."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any

from pydantic import Field

from acr.candidates import ChangeOccurrence, ReadOccurrence
from acr.contracts import ContractModel, EvidenceRef, InformationLabel

ADAPTER_VERSION = "multi_swe_bench_flash_openhands_v1"
SOURCE_ID = "multi_swe_bench_flash_openhands"
_FILE_HEADER = re.compile(r"^Here's the result of running `cat -n` on (.+):\n")
_NUMBERED_LINE = re.compile(r"^\s*\d+\t")


class AdaptedTrajectory(ContractModel):
    """Only the fields required by the offline duplicate-read audit."""

    trajectory_id: str
    task_id: str
    repository: str
    event_count: int = Field(ge=0)
    read_occurrences: list[ReadOccurrence]
    changes: list[ChangeOccurrence]
    unsupported_read_count: int = Field(ge=0)
    observed_input_tokens: int | None = Field(default=None, ge=0)
    input_usage_complete: bool


def _ref(raw_hash: str, trajectory_id: str, locator: str) -> EvidenceRef:
    return EvidenceRef(
        blob_hash=raw_hash,
        source_id=SOURCE_ID,
        trajectory_key=trajectory_id,
        locator=locator,
        labels=[InformationLabel(scope="analysis")],
    )


def _normalize_path(path: object) -> str | None:
    if not isinstance(path, str) or not path.startswith("/workspace/"):
        return None
    parts = PurePosixPath(path).parts
    if ".." in parts or len(parts) < 4:
        return None
    return PurePosixPath(*parts[3:]).as_posix()


def _file_output(content: object, path: object, args: dict[str, Any]) -> tuple[str, int, bool] | None:
    if not isinstance(content, str) or not isinstance(path, str):
        return None
    match = _FILE_HEADER.match(content)
    if match is None or match.group(1) != path:
        return None
    body = content[match.end() :]
    lines = body.splitlines(keepends=True)
    numbered = all(_NUMBERED_LINE.match(line.rstrip("\r\n")) for line in lines)
    complete = (
        args.get("start") == 0
        and args.get("end") == -1
        and args.get("view_range") is None
        and numbered
    )
    raw = content.encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), len(raw), complete


def _task_parts(trajectory_id: str) -> tuple[str, str]:
    repository = trajectory_id.rsplit("-", 1)[0]
    return trajectory_id, repository


def _validate_events(document: object) -> list[dict[str, Any]]:
    if not isinstance(document, list):
        raise TypeError("unsupported Multi-SWE-bench OpenHands trajectory root")
    events: list[dict[str, Any]] = []
    identifiers: set[int] = set()
    for event in document:
        if not isinstance(event, dict):
            raise TypeError("unsupported Multi-SWE-bench OpenHands event")
        identifier = event.get("id")
        if (
            not isinstance(identifier, int)
            or identifier in identifiers
            or not isinstance(event.get("source"), str)
            or not isinstance(event.get("message"), str)
        ):
            raise ValueError("unsupported Multi-SWE-bench OpenHands event identity")
        action = event.get("action")
        if action is not None and (
            not isinstance(action, str) or not isinstance(event.get("args"), dict)
        ):
            raise ValueError("unsupported Multi-SWE-bench OpenHands action")
        identifiers.add(identifier)
        events.append(event)
    return events


def _observed_input_usage(events: list[dict[str, Any]]) -> tuple[int | None, bool]:
    usages: dict[str, int] = {}
    saw_model_response = False
    complete = True
    for event in events:
        metadata = event.get("tool_call_metadata")
        if not isinstance(metadata, dict):
            continue
        response = metadata.get("model_response")
        if not isinstance(response, dict):
            continue
        saw_model_response = True
        response_id = response.get("id")
        usage = response.get("usage")
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        if not isinstance(response_id, str) or not isinstance(prompt_tokens, int):
            complete = False
            continue
        previous = usages.get(response_id)
        if previous is not None and previous != prompt_tokens:
            complete = False
            continue
        usages[response_id] = prompt_tokens
    if not saw_model_response or not complete:
        return None, False
    return sum(usages.values()), True


def adapt_trajectory(raw: bytes, trajectory_id: str) -> AdaptedTrajectory:
    """Parse one real event-list artifact without inferring missing request state."""

    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Multi-SWE-bench OpenHands JSON") from exc
    events = _validate_events(document)
    raw_hash = hashlib.sha256(raw).hexdigest()
    results_by_cause: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    for position, event in enumerate(events):
        cause = event.get("cause")
        if isinstance(cause, int):
            results_by_cause.setdefault(cause, []).append((position, event))

    reads: list[ReadOccurrence] = []
    changes: list[ChangeOccurrence] = []
    unsupported = 0
    for position, event in enumerate(events):
        action = event.get("action")
        args = event.get("args")
        if action == "read" and isinstance(args, dict):
            path = args.get("path")
            normalized_path = _normalize_path(path)
            matching = [
                item
                for item in results_by_cause.get(event["id"], [])
                if item[1].get("observation") == "read"
            ]
            parsed = None
            result_position = None
            refs = [_ref(raw_hash, trajectory_id, f"/{position}")]
            reason = None
            if len(matching) == 1:
                result_position, result = matching[0]
                parsed = _file_output(result.get("content"), path, args)
                refs.append(_ref(raw_hash, trajectory_id, f"/{result_position}/content"))
                if parsed is None:
                    reason = "read_result_not_complete_file_content"
            else:
                reason = "read_result_missing_or_ambiguous"
            if normalized_path is None or parsed is None:
                unsupported += 1
                continue
            output_hash, output_bytes, complete = parsed
            reads.append(
                ReadOccurrence(
                    trajectory_id=trajectory_id,
                    occurrence_id=f"event:{event['id']}",
                    source_position=position,
                    result_position=result_position,
                    normalized_path=normalized_path,
                    output_sha256=output_hash,
                    output_bytes=output_bytes,
                    file_sha256=None,
                    complete=complete,
                    encoding=None,
                    request_membership_observed=None,
                    current_file_sha256=None,
                    evidence_refs=refs,
                    unsupported_reason=reason,
                )
            )
        elif action == "edit" and isinstance(args, dict):
            changes.append(
                ChangeOccurrence(
                    occurrence_id=f"event:{event['id']}",
                    source_position=position,
                    kind="edit",
                    normalized_path=_normalize_path(args.get("path")),
                    evidence_refs=[_ref(raw_hash, trajectory_id, f"/{position}")],
                )
            )
        elif action == "run":
            changes.append(
                ChangeOccurrence(
                    occurrence_id=f"event:{event['id']}",
                    source_position=position,
                    kind="unknown_change",
                    evidence_refs=[_ref(raw_hash, trajectory_id, f"/{position}")],
                )
            )
    task_id, repository = _task_parts(trajectory_id)
    input_tokens, input_usage_complete = _observed_input_usage(events)
    return AdaptedTrajectory(
        trajectory_id=trajectory_id,
        task_id=task_id,
        repository=repository,
        event_count=len(events),
        read_occurrences=reads,
        changes=changes,
        unsupported_read_count=unsupported,
        observed_input_tokens=input_tokens,
        input_usage_complete=input_usage_complete,
    )
