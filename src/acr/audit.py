"""Fail-closed audit of persisted M1 artifacts only."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from acr.adapters.legacy import ADAPTER_VERSION, parse_document
from acr.contracts import Event, EvidenceRef, FileBinding, Provenance, RequestSnapshot, Run
from acr.provenance import resolve_json_pointer
from acr.store import (
    load_blob,
    load_import,
    load_normalized,
    load_producer,
    load_producer_manifest,
    load_provenance,
    load_run_json,
)

_FIELDS = ("action", "observation", "response")
_REQUIRED_MANIFEST = (
    "source_type",
    "upstream_repository",
    "upstream_commit",
    "artifact_path",
    "instance_id",
    "raw_sha256",
)
_REQUIRED_PRODUCER = (
    "producer_kind",
    "code_revision",
    "adapter_name",
    "adapter_version",
    "schema_version",
    "config_identity",
    "created_at",
)
_PINNED_SOURCE_IDENTITY = {
    "source_type": "official_demonstration_trajectory",
    "upstream_repository": "https://github.com/multi-swe-bench/MSWE-agent",
    "upstream_commit": "88217624b637646b886cb0462995c07559e96f58",
    "artifact_path": (
        "trajectories/demonstrations/"
        "replay__marshmallow-code__marshmallow-1867__default__t-0.20__p-0.95__c-2.00__"
        "install-1___install_from_source/marshmallow-code__marshmallow-1867.traj"
    ),
    "instance_id": "marshmallow-code__marshmallow-1867",
    "raw_sha256": "7112504a1d783755f97fa6c8dec4bb4f8e596627c8100f356c9eda82d057c770",
}


@dataclass(frozen=True)
class AuditResult:
    status: str
    blocks: tuple[str, ...]


def _digest_matches(value: bytes, expected: str) -> bool:
    return hashlib.sha256(value).hexdigest() == expected


def _load_ref_blob(root: Path, ref: EvidenceRef, blocks: list[str]) -> bytes | None:
    try:
        value = load_blob(root, ref.blob_hash)
    except (FileNotFoundError, OSError):
        blocks.append("referenced_blob_missing")
        return None
    if not _digest_matches(value, ref.blob_hash):
        blocks.append("referenced_blob_hash_invalid")
        return None
    return value


def _valid_manifest(manifest: Any) -> bool:
    return isinstance(manifest, dict) and all(
        isinstance(manifest.get(key), str) and manifest[key].strip() for key in _REQUIRED_MANIFEST
    )


def _pinned_source_matches(manifest: Any) -> bool:
    return isinstance(manifest, dict) and all(
        manifest.get(key) == value for key, value in _PINNED_SOURCE_IDENTITY.items()
    )


def _valid_producer_manifest(manifest: Any) -> bool:
    return (
        isinstance(manifest, dict)
        and all(isinstance(manifest.get(key), str) and manifest[key].strip() for key in _REQUIRED_PRODUCER)
        and manifest.get("adapter_version") == ADAPTER_VERSION
        and manifest.get("schema_version") == "1.0"
    )


def _audit(root: Path, import_id: str, blocks: list[str]) -> None:
    try:
        manifest, raw_ref = load_import(root, import_id)
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValidationError, ValueError):
        blocks.append("malformed_persisted_evidence")
        return
    if not _valid_manifest(manifest):
        blocks.append("source_manifest_incomplete")
    if not _pinned_source_matches(manifest):
        blocks.append("pinned_source_identity_mismatch")
    if (
        raw_ref.source_id != "mswe_agent_demo"
        or raw_ref.trajectory_key != manifest.get("instance_id")
        or raw_ref.blob_hash != manifest.get("raw_sha256")
        or raw_ref.locator != ""
    ):
        blocks.append("source_identity_mismatch")

    raw = _load_ref_blob(root, raw_ref, blocks)
    if raw is None:
        return
    try:
        document = parse_document(raw)
    except (TypeError, ValueError):
        blocks.append("malformed_raw_schema")
        return

    try:
        normalized = load_normalized(root, import_id)
        producer_ref = load_producer(root, import_id)
        producer_file = load_producer_manifest(root, import_id)
        provenance = load_provenance(root, import_id)
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValidationError, ValueError):
        blocks.append("malformed_persisted_evidence")
        return

    producer_blob = _load_ref_blob(root, producer_ref, blocks)
    if producer_blob is None:
        return
    if producer_ref.source_id != "acr_producer_manifest" or producer_ref.trajectory_key != import_id:
        blocks.append("producer_identity_mismatch")
    if producer_blob != producer_file:
        blocks.append("producer_manifest_mismatch")
    try:
        producer_manifest = json.loads(producer_blob)
    except (UnicodeDecodeError, json.JSONDecodeError):
        blocks.append("malformed_persisted_evidence")
        return
    if not _valid_producer_manifest(producer_manifest):
        blocks.append("producer_manifest_incomplete")

    raw_steps = document["trajectory"]
    if normalized.adapter_version != ADAPTER_VERSION:
        blocks.append("normalized_adapter_mismatch")
    if normalized.producer_ref != producer_ref:
        blocks.append("producer_identity_mismatch")
    if normalized.environment != document["environment"]:
        blocks.append("normalized_environment_mismatch")
    if len(normalized.steps) != len(raw_steps):
        blocks.append("normalized_structure_mismatch")

    for index, raw_step in enumerate(raw_steps):
        if index >= len(normalized.steps):
            continue
        step = normalized.steps[index]
        if step.source_position != index:
            blocks.append("source_position_mismatch")
        for field in _FIELDS:
            if getattr(step, field) != raw_step[field]:
                blocks.append("normalized_value_mismatch")

    expected = {(f"step:{index}", field) for index in range(len(raw_steps)) for field in _FIELDS}
    groups: dict[tuple[str, str], list[Provenance]] = {}
    for item in provenance:
        groups.setdefault((item.output_object, item.field), []).append(item)
    if set(groups) != expected:
        blocks.append("required_provenance_missing")

    for key, items in groups.items():
        if len(items) != 1:
            blocks.append("conflicting_provenance")
            continue
        output_object, field = key
        if key not in expected:
            continue
        item = items[0]
        if item.producer_ref != producer_ref:
            blocks.append("producer_identity_mismatch")
        if len(item.input_refs) != 1:
            blocks.append("provenance_input_mismatch")
            continue
        index = int(output_object.split(":", maxsplit=1)[1])
        ref = item.input_refs[0]
        if ref.blob_hash != raw_ref.blob_hash:
            blocks.append("provenance_raw_blob_mismatch")
        if ref.source_id != raw_ref.source_id or ref.trajectory_key != raw_ref.trajectory_key:
            blocks.append("source_identity_mismatch")
        expected_locator = f"/trajectory/{index}/{field}"
        locator_matches_position = ref.locator == expected_locator
        if not locator_matches_position:
            blocks.append("provenance_position_mismatch")
        referenced = _load_ref_blob(root, ref, blocks)
        if referenced is None:
            continue
        try:
            value = resolve_json_pointer(json.loads(referenced), ref.locator)
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
            blocks.append("invalid_locator")
            continue
        if not locator_matches_position:
            continue
        if index >= len(normalized.steps) or getattr(normalized.steps[index], field) != value:
            blocks.append("normalized_value_mismatch")


def audit(root: Path, import_id: str) -> AuditResult:
    """Audit only stored artifacts; never invoke normalization during audit."""

    blocks: list[str] = []
    try:
        _audit(root, import_id, blocks)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        blocks.append("malformed_persisted_evidence")
    return AuditResult("BLOCK" if blocks else "PASS", tuple(sorted(set(blocks))))


def _runtime_ref(root: Path, run_id: str, ref: EvidenceRef, blocks: list[str]) -> bytes | None:
    if ref.source_id != "acr_runtime" or ref.trajectory_key != run_id:
        blocks.append("wrong_run_evidence_reference")
        return None
    return _load_ref_blob(root, ref, blocks)


def _load_json_ref(root: Path, run_id: str, ref: EvidenceRef, blocks: list[str]) -> Any | None:
    raw = _runtime_ref(root, run_id, ref, blocks)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        blocks.append("malformed_persisted_runtime_evidence")
        return None


def _load_jsonl_models(path: Path, model: type, blocks: list[str]) -> list[Any] | None:
    try:
        return [model.model_validate_json(line) for line in path.read_text().splitlines()]
    except (FileNotFoundError, OSError, ValidationError, ValueError):
        blocks.append("malformed_persisted_runtime_evidence")
        return None


def _audit_runtime(root: Path, run_id: str, blocks: list[str]) -> None:
    run_root = root / "runs" / run_id
    try:
        run = Run.model_validate(load_run_json(root, run_id, "run.json"))
        initial = load_run_json(root, run_id, "initial_state.json")
        final = load_run_json(root, run_id, "final_state.json")
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValidationError, ValueError):
        blocks.append("malformed_persisted_runtime_evidence")
        return
    if run.id != run_id or run.events_ref.locator != "/events.jsonl":
        blocks.append("runtime_run_identity_mismatch")
    events = _load_jsonl_models(run_root / "events.jsonl", Event, blocks)
    snapshots = _load_jsonl_models(run_root / "requests.jsonl", RequestSnapshot, blocks)
    bindings = _load_jsonl_models(run_root / "file_bindings.jsonl", FileBinding, blocks)
    if events is None or snapshots is None or bindings is None:
        return
    event_blob = _runtime_ref(root, run_id, run.events_ref, blocks)
    expected_events = b"".join(event.model_dump_json().encode() + b"\n" for event in events)
    if event_blob is not None and event_blob != expected_events:
        blocks.append("events_artifact_mismatch")
    if not events or events[-1].kind != "run_stop":
        blocks.append("run_not_closed")
    if [event.event_seq for event in events] != list(range(len(events))):
        blocks.append("runtime_event_sequence_mismatch")
    if any(event.run_id != run_id for event in events):
        blocks.append("wrong_run_evidence_reference")
    payloads: dict[int, Any] = {}
    starts: set[str] = set()
    finishes: set[str] = set()
    for event in events:
        payload = _load_json_ref(root, run_id, event.payload_ref, blocks)
        if payload is None:
            continue
        payloads[event.event_seq] = payload
        if event.kind == "tool_start" and event.call_id:
            starts.add(event.call_id)
        if event.kind == "tool_finish" and event.call_id:
            finishes.add(event.call_id)
            if event.available_seq != event.event_seq:
                blocks.append("unfinished_tool_result_visible")
    if starts != finishes:
        blocks.append("incomplete_tool_call")
    _audit_requests(root, run_id, snapshots, events, payloads, blocks)
    _audit_file_bindings(root, run_id, bindings, events, payloads, blocks)
    if initial.get("run_id") != run_id or final.get("run_id") != run_id:
        blocks.append("wrong_run_evidence_reference")
    if initial.get("state_caps", {}).get("initial_repository") != "verified":
        blocks.append("initial_workspace_not_verified")
    if run.sealed_artifact_ref is None or run.sealed_artifact_hash is None:
        blocks.append("run_not_sealed")
    elif _runtime_ref(root, run_id, run.sealed_artifact_ref, blocks) is not None:
        actual = hashlib.sha256(_runtime_ref(root, run_id, run.sealed_artifact_ref, blocks) or b"").hexdigest()
        if actual != run.sealed_artifact_hash:
            blocks.append("sealed_artifact_hash_mismatch")


def _audit_requests(
    root: Path,
    run_id: str,
    snapshots: list[RequestSnapshot],
    events: list[Event],
    payloads: dict[int, Any],
    blocks: list[str],
) -> None:
    attempt_ids = [snapshot.attempt_id for snapshot in snapshots]
    if len(attempt_ids) != len(set(attempt_ids)):
        blocks.append("provider_attempt_merged")
    request_events = {payload.get("attempt_id"): payload for event, payload in ((event, payloads.get(event.event_seq)) for event in events) if event.kind == "request" and isinstance(payload, dict)}
    response_events = {payload.get("attempt_id"): payload for event, payload in ((event, payloads.get(event.event_seq)) for event in events) if event.kind == "response" and isinstance(payload, dict)}
    for snapshot in snapshots:
        if snapshot.run_id != run_id:
            blocks.append("wrong_run_evidence_reference")
            continue
        request = request_events.get(snapshot.attempt_id)
        response = response_events.get(snapshot.attempt_id)
        if request is None or response is None:
            blocks.append("provider_attempt_missing_event")
            continue
        for name, ref in (("before_body_ref", snapshot.before_body_ref), ("prepared_body_ref", snapshot.prepared_body_ref), ("sent_body_ref", snapshot.sent_body_ref)):
            if ref is None or _runtime_ref(root, run_id, ref, blocks) is None:
                blocks.append("request_evidence_missing")
                continue
            if request.get(name) != ref.model_dump():
                blocks.append("request_send_boundary_mismatch")
        raw_response = response.get("raw_response_ref")
        if not isinstance(raw_response, dict):
            blocks.append("provider_attempt_missing_event")
            continue
        try:
            response_ref = EvidenceRef.model_validate(raw_response)
        except ValidationError:
            blocks.append("malformed_persisted_runtime_evidence")
            continue
        response_bytes = _runtime_ref(root, run_id, response_ref, blocks)
        usage = response.get("usage")
        usage_ref_raw = response.get("raw_usage_ref")
        if response_bytes is None:
            continue
        try:
            response_json = json.loads(response_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError):
            response_json = None
        has_usage = isinstance(response_json, dict) and isinstance(response_json.get("usage"), dict)
        if has_usage:
            if not isinstance(usage, dict) or usage.get("status") != "observed" or not isinstance(usage_ref_raw, dict):
                blocks.append("provider_usage_not_observed")
        elif not isinstance(usage, dict) or usage.get("status") != "unknown" or usage.get("value") is not None:
            blocks.append("provider_usage_invented")


def _audit_file_bindings(
    root: Path,
    run_id: str,
    bindings: list[FileBinding],
    events: list[Event],
    payloads: dict[int, Any],
    blocks: list[str],
) -> None:
    finishes = {event.id: payloads.get(event.event_seq) for event in events if event.kind == "tool_finish"}
    for binding in bindings:
        result = finishes.get(binding.read_event_id)
        if not isinstance(result, dict) or result.get("complete") is not True:
            blocks.append("file_binding_without_closed_tool")
            continue
        try:
            ref = EvidenceRef.model_validate(result["body_ref"])
        except (KeyError, ValidationError):
            blocks.append("malformed_persisted_runtime_evidence")
            continue
        raw = _runtime_ref(root, run_id, ref, blocks)
        if raw is None:
            continue
        if hashlib.sha256(raw).hexdigest() != binding.file_sha256 or result.get("sha256") != binding.file_sha256:
            blocks.append("file_binding_bytes_mismatch")
        if result.get("path") != binding.repo_relative_path or binding.observed_seq < 0:
            blocks.append("file_binding_identity_mismatch")


def audit_run(root: Path, run_id: str) -> AuditResult:
    """Fail closed over persisted M2 artifacts; it never executes a runtime."""

    blocks: list[str] = []
    try:
        _audit_runtime(root, run_id, blocks)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        blocks.append("malformed_persisted_runtime_evidence")
    return AuditResult("BLOCK" if blocks else "PASS", tuple(sorted(set(blocks))))
