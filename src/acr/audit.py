"""Fail-closed audit of persisted M1 artifacts only."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from acr.adapters.legacy import ADAPTER_VERSION, parse_document
from acr.adapters.provider import extract_deepseek_message_content
from acr.contracts import (
    ContextBlock,
    CostEntry,
    DecisionView,
    EvaluationResult,
    Event,
    EvidenceRef,
    Fact,
    FileBinding,
    InformationLabel,
    Pair,
    PhysicalAttempt,
    Provenance,
    RepositoryState,
    RequestSnapshot,
    Run,
)
from acr.provenance import resolve_json_pointer
from acr.state import tree_manifest_hash
from acr.store import (
    load_blob,
    load_import,
    load_normalized,
    load_pair_json,
    load_producer,
    load_producer_manifest,
    load_provenance,
    load_run_json,
)
from acr.visibility import VisibilityViolation, build_view

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
        initial = RepositoryState.model_validate(load_run_json(root, run_id, "initial_state.json"))
        final = RepositoryState.model_validate(load_run_json(root, run_id, "final_state.json"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValidationError, ValueError):
        blocks.append("malformed_persisted_runtime_evidence")
        return
    if run.id != run_id or run.events_ref.locator != "/events.jsonl":
        blocks.append("runtime_run_identity_mismatch")
    producer = _load_runtime_producer(root, run_id, run, blocks)
    _audit_repository_states(root, run_id, run, initial, final, producer, blocks)
    events = _load_jsonl_models(run_root / "events.jsonl", Event, blocks)
    snapshots = _load_jsonl_models(run_root / "requests.jsonl", RequestSnapshot, blocks)
    bindings = _load_jsonl_models(run_root / "file_bindings.jsonl", FileBinding, blocks)
    physical_attempts = _load_physical_attempts(run_root, blocks)
    if events is None or snapshots is None or bindings is None or physical_attempts is None:
        return
    _audit_runtime_config(root, run_id, run, blocks)
    event_blob = _runtime_ref(root, run_id, run.events_ref, blocks)
    expected_events = b"".join(event.model_dump_json().encode() + b"\n" for event in events)
    if event_blob is not None and event_blob != expected_events:
        blocks.append("events_artifact_mismatch")
    if not events or events[-1].kind != "run_stop":
        blocks.append("run_not_closed")
    if [event.event_seq for event in events] != list(range(len(events))):
        blocks.append("runtime_event_sequence_mismatch")
    for event in events:
        if event.run_id != run_id or event.producer_ref != producer:
            blocks.append("wrong_run_evidence_reference")
        if event.id != f"event:{run_id}:{event.event_seq}":
            blocks.append("runtime_event_identity_mismatch")
        if event.payload_ref.locator != f"/events/{event.event_seq}/payload":
            blocks.append("runtime_event_payload_mismatch")
    payloads: dict[int, Any] = {}
    for event in events:
        payload = _load_json_ref(root, run_id, event.payload_ref, blocks)
        if payload is None:
            continue
        payloads[event.event_seq] = payload
    _audit_requests(root, run_id, snapshots, events, payloads, physical_attempts, producer, run, blocks)
    _audit_file_bindings(root, run_id, bindings, events, payloads, final, blocks)
    _audit_decision_views(root, run_id, run, producer, events, payloads, snapshots, blocks)
    _audit_usage_ledger(root, run_id, snapshots, events, payloads, blocks)


def _audit_usage_ledger(
    root: Path, run_id: str, snapshots: list[RequestSnapshot], events: list[Event], payloads: dict[int, Any], blocks: list[str]
) -> None:
    """Ensure persisted normalized token totals are rebuildable from terminal evidence."""
    try:
        entries = _load_jsonl_models(root / "runs" / run_id / "usage_ledger.jsonl", CostEntry, blocks)
        aggregate = load_run_json(root, run_id, "usage_aggregate.json")
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError):
        blocks.append("usage_ledger_missing")
        return
    if entries is None or not isinstance(aggregate, dict):
        blocks.append("usage_ledger_malformed")
        return
    expected_ids = {snapshot.attempt_id for snapshot in snapshots}
    if aggregate.get("physical_attempt_count") != len(expected_ids):
        blocks.append("usage_aggregate_mismatch")
    if {entry.attempt_id for entry in entries} != expected_ids:
        blocks.append("usage_ledger_attempt_mismatch")
    terminal = {
        payload.get("attempt_id"): payload
        for event in events
        for payload in [payloads.get(event.event_seq)]
        if event.kind in {"response", "provider_failure"} and isinstance(payload, dict)
    }
    totals = {"input_tokens": 0.0, "output_tokens": 0.0, "total_tokens": 0.0}
    complete = True
    for attempt_id in expected_ids:
        usage = terminal.get(attempt_id, {}).get("usage")
        try:
            fact = Fact[dict].model_validate(usage)
        except ValidationError:
            blocks.append("usage_ledger_malformed")
            continue
        if fact.status != "observed" or not isinstance(fact.value, dict):
            complete = False
            continue
        raw = fact.value
        values = {"input_tokens": raw.get("input_tokens", raw.get("prompt_tokens")), "output_tokens": raw.get("output_tokens", raw.get("completion_tokens")), "total_tokens": raw.get("total_tokens")}
        if values["total_tokens"] is None and all(isinstance(values[x], (int, float)) for x in ("input_tokens", "output_tokens")):
            values["total_tokens"] = values["input_tokens"] + values["output_tokens"]
        for key, value in values.items():
            if isinstance(value, (int, float)):
                totals[key] += float(value)
            else:
                complete = False
    if aggregate.get("usage_complete") != complete or any(aggregate.get(key) != (value if complete else None) for key, value in totals.items()):
        blocks.append("usage_aggregate_mismatch")


def _load_runtime_producer(root: Path, run_id: str, run: Run, blocks: list[str]) -> EvidenceRef:
    try:
        persisted_ref = EvidenceRef.model_validate(load_run_json(root, run_id, "producer_ref.json"))
        persisted_file = (root / "runs" / run_id / "producer_manifest.json").read_bytes()
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValidationError, ValueError):
        blocks.append("malformed_persisted_runtime_evidence")
        return run.producer_ref
    producer_blob = _runtime_ref(root, run_id, persisted_ref, blocks)
    if (
        persisted_ref.source_id != "acr_runtime"
        or persisted_ref.trajectory_key != run_id
        or persisted_ref.locator != "/producer-manifest"
        or run.producer_ref != persisted_ref
        or producer_blob != persisted_file
    ):
        blocks.append("runtime_producer_mismatch")
    if producer_blob is None:
        return persisted_ref
    try:
        manifest = json.loads(producer_blob)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        blocks.append("runtime_producer_malformed")
        return persisted_ref
    required = ("producer_kind", "code_revision", "schema_version", "runtime_version")
    if (
        not isinstance(manifest, dict)
        or any(not isinstance(manifest.get(key), str) or not manifest[key].strip() for key in required)
        or manifest.get("schema_version") != "1.0"
        or manifest.get("runtime_version") != "m2_capture_v1"
    ):
        blocks.append("runtime_producer_manifest_invalid")
    return persisted_ref


def _load_physical_attempts(run_root: Path, blocks: list[str]) -> list[PhysicalAttempt] | None:
    directory = run_root / "physical_attempts"
    if not directory.exists():
        # A run with no provider calls has no physical-attempt inventory.  The
        # set comparison in _audit_requests rejects its absence when any
        # normalized provider attempt exists.
        return []
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError:
        blocks.append("physical_attempt_inventory_missing")
        return None
    if not paths:
        return []
    try:
        return [PhysicalAttempt.model_validate_json(path.read_text()) for path in paths]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        blocks.append("malformed_persisted_runtime_evidence")
        return None


def _audit_runtime_config(root: Path, run_id: str, run: Run, blocks: list[str]) -> None:
    if run.config_ref.locator != "/config" or _runtime_ref(root, run_id, run.config_ref, blocks) is None:
        blocks.append("runtime_config_reference_mismatch")


def _audit_repository_states(
    root: Path,
    run_id: str,
    run: Run,
    initial: RepositoryState,
    final: RepositoryState,
    producer: EvidenceRef,
    blocks: list[str],
) -> None:
    for state, phase, state_ref in (
        (initial, "initial", run.initial_state_ref),
        (final, "final", run.final_state_ref),
    ):
        if state_ref is None:
            blocks.append("repository_state_reference_missing")
            continue
        if state_ref.locator != f"/{phase}_state.json":
            blocks.append("repository_state_reference_mismatch")
        raw_state = _runtime_ref(root, run_id, state_ref, blocks)
        path = root / "runs" / run_id / f"{phase}_state.json"
        try:
            file_state = path.read_bytes()
        except OSError:
            blocks.append("malformed_persisted_runtime_evidence")
            continue
        if raw_state != file_state:
            blocks.append("repository_state_artifact_mismatch")
        if state.run_id != run_id or state.producer_ref != producer:
            blocks.append("repository_state_identity_mismatch")
        if state.state_phase != phase or state.tree_ref is None:
            blocks.append("repository_state_phase_mismatch")
            continue
        if state.tree_ref.locator != f"/state/{phase}-tree":
            blocks.append("repository_tree_reference_mismatch")
            if phase == "final":
                blocks.append("final_state_sealed_artifact_mismatch")
        tree_raw = _runtime_ref(root, run_id, state.tree_ref, blocks)
        if tree_raw is None:
            continue
        try:
            tree = json.loads(tree_raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            blocks.append("malformed_persisted_runtime_evidence")
            continue
        expected_hash = tree_manifest_hash(tree) if isinstance(tree, dict) else None
        recorded_hash = state.initial_tree_hash if phase == "initial" else state.final_tree_hash
        if expected_hash != recorded_hash:
            blocks.append("repository_tree_hash_mismatch")
    if initial.state_caps.get("initial_repository") != "verified":
        blocks.append("initial_workspace_not_verified")
    if run.sealed_artifact_ref is None or run.sealed_artifact_hash is None:
        blocks.append("run_not_sealed")
    else:
        sealed = _runtime_ref(root, run_id, run.sealed_artifact_ref, blocks)
        if sealed is not None and hashlib.sha256(sealed).hexdigest() != run.sealed_artifact_hash:
            blocks.append("sealed_artifact_hash_mismatch")
        try:
            artifact = json.loads(sealed) if sealed is not None else None
            entries = artifact["files"] if isinstance(artifact, dict) else None
            if not isinstance(entries, list):
                raise TypeError("sealed files must be a list")
            tree = {"files": [{key: item[key] for key in ("path", "mode", "sha256")} for item in entries]}
            if tree_manifest_hash(tree) != final.final_tree_hash:
                blocks.append("final_state_sealed_artifact_mismatch")
            for item in entries:
                ref = EvidenceRef.model_validate(item["body_ref"])
                body = _runtime_ref(root, run_id, ref, blocks)
                if body is None or hashlib.sha256(body).hexdigest() != item["sha256"]:
                    blocks.append("sealed_artifact_file_mismatch")
        except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
            blocks.append("sealed_artifact_malformed")


def _same_evidence_occurrence(left: EvidenceRef, right: EvidenceRef) -> bool:
    return (
        left.blob_hash == right.blob_hash
        and left.source_id == right.source_id
        and left.trajectory_key == right.trajectory_key
        and left.locator == right.locator
    )


def _canonical_event_labels(event: Event) -> list[InformationLabel]:
    taints = sorted(
        {
            taint
            for label in event.payload_ref.labels
            for taint in label.taints
        }
    )
    return [
        InformationLabel(
            scope="runtime",
            run_id=event.run_id,
            available_seq=event.available_seq,
            taints=taints,
        )
    ]


def _context_blob(root: Path, ref: EvidenceRef, blocks: list[str]) -> bytes | None:
    raw = _load_ref_blob(root, ref, blocks)
    if raw is None:
        return None
    if not ref.labels:
        blocks.append("context_unknown_authorization")
    return raw


def _audit_context_block(
    root: Path,
    run: Run,
    block: ContextBlock,
    message: dict[str, Any],
    events: list[Event],
    payloads: dict[int, Any],
    blocks: list[str],
) -> None:
    ref = block.provenance_ref
    if ref is None:
        blocks.append("context_provenance_missing")
        return
    raw = _context_blob(root, ref, blocks)
    if raw is None:
        return
    content = message.get("content")
    if not isinstance(content, str):
        blocks.append("request_context_mapping_mismatch")
        return
    if block.type == "system_prompt":
        if (
            block.origin_event_id != "public:system:deepseek_command_protocol_v1"
            or ref.source_id != "acr_runtime_config"
            or ref.trajectory_key != "deepseek_command_protocol_v1"
            or ref.locator != "/system-prompt"
            or raw != content.encode()
            or ref.labels != [InformationLabel(scope="public")]
        ):
            blocks.append("context_origin_occurrence_mismatch")
        return
    if block.type == "task_instruction":
        if (
            block.origin_event_id != f"public-task:{run.task_id}:instruction"
            or ref.source_id != "acr_public_task"
            or ref.trajectory_key != run.task_id
            or ref.locator != "/public-instruction"
            or raw != content.encode()
            or ref.labels != [InformationLabel(scope="public")]
        ):
            blocks.append("context_origin_occurrence_mismatch")
        return
    matches = [event for event in events if event.id == block.origin_event_id]
    if len(matches) != 1:
        blocks.append("context_origin_occurrence_mismatch")
        return
    event = matches[0]
    payload = payloads.get(event.event_seq)
    if not isinstance(payload, dict):
        blocks.append("context_origin_occurrence_mismatch")
        return
    if ref.labels != _canonical_event_labels(event):
        blocks.append("context_provenance_label_mismatch")
    if block.type == "assistant_response":
        try:
            payload_ref = EvidenceRef.model_validate(payload["raw_response_ref"])
        except (KeyError, ValidationError):
            blocks.append("context_origin_occurrence_mismatch")
            return
        if (
            event.kind != "response"
            or event.call_id is None
            or not _same_evidence_occurrence(ref, payload_ref)
            or extract_deepseek_message_content(raw) != content
        ):
            blocks.append("context_origin_occurrence_mismatch")
        return
    if block.type != "tool_result" or event.kind != "tool_finish":
        blocks.append("context_origin_occurrence_mismatch")
        return
    try:
        body_ref = EvidenceRef.model_validate(payload["body_ref"])
    except (KeyError, ValidationError):
        blocks.append("context_origin_occurrence_mismatch")
        return
    if event.call_id != block.tool_call_id or not _same_evidence_occurrence(ref, body_ref):
        blocks.append("context_origin_occurrence_mismatch")
        return
    tool = payload.get("tool")
    if tool == "read_file":
        expected = f"TOOL RESULT read_file {payload.get('path')}:\n{raw.decode('utf-8')}"
        if (
            block.file_binding is None
            or block.file_binding.read_event_id != event.id
            or block.file_binding.observed_seq != event.available_seq
            or expected != content
        ):
            blocks.append("request_context_occurrence_mismatch")
    elif tool == "write_file":
        if block.file_binding is not None or content != "TOOL RESULT write_file completed":
            blocks.append("request_context_occurrence_mismatch")
    elif tool == "run_test":
        try:
            expected = f"TOOL RESULT run_test: {json.dumps(json.loads(raw), sort_keys=True)}"
        except (UnicodeDecodeError, json.JSONDecodeError):
            blocks.append("request_context_occurrence_mismatch")
            return
        if block.file_binding is not None or content != expected:
            blocks.append("request_context_occurrence_mismatch")
    else:
        blocks.append("request_context_occurrence_mismatch")


def _audit_requests(
    root: Path,
    run_id: str,
    snapshots: list[RequestSnapshot],
    events: list[Event],
    payloads: dict[int, Any],
    physical_attempts: list[PhysicalAttempt],
    producer: EvidenceRef,
    run: Run,
    blocks: list[str],
) -> None:
    request_events = [(event, payloads.get(event.event_seq)) for event in events if event.kind == "request"]
    terminal_events = [
        (event, payloads.get(event.event_seq))
        for event in events
        if event.kind in {"response", "provider_failure"}
    ]
    snapshot_ids = [snapshot.attempt_id for snapshot in snapshots]
    request_ids = [payload.get("attempt_id") for _, payload in request_events if isinstance(payload, dict)]
    terminal_ids = [payload.get("attempt_id") for _, payload in terminal_events if isinstance(payload, dict)]
    if any(not isinstance(value, str) for value in request_ids + terminal_ids):
        blocks.append("malformed_persisted_runtime_evidence")
        return
    for ids, reason in (
        (snapshot_ids, "duplicate_attempt_id"),
        (request_ids, "duplicate_request_event"),
        (terminal_ids, "duplicate_terminal_event"),
    ):
        if len(ids) != len(set(ids)):
            blocks.append(reason)
    snapshot_set, request_set, terminal_set = set(snapshot_ids), set(request_ids), set(terminal_ids)
    if snapshot_set != request_set or snapshot_set != terminal_set:
        blocks.append("attempt_set_mismatch")
    if request_set - snapshot_set:
        blocks.append("orphan_request_event")
    if terminal_set - snapshot_set:
        blocks.append("orphan_terminal_event")
    if snapshot_set - request_set or snapshot_set - terminal_set:
        blocks.append("attempt_occurrence_missing")
    physical = _physical_attempt_index(physical_attempts, run_id, producer, root, blocks)
    physical_set = set(physical)
    if physical_set != snapshot_set or physical_set != request_set or physical_set != terminal_set:
        blocks.append("physical_attempt_inventory_mismatch")
    if physical_set - snapshot_set:
        blocks.append("orphan_physical_attempt")
    if snapshot_set - physical_set or request_set - physical_set or terminal_set - physical_set:
        blocks.append("normalized_attempt_without_physical_evidence")
    request_by_id = {payload["attempt_id"]: (event, payload) for event, payload in request_events if isinstance(payload, dict)}
    terminal_by_id = {payload["attempt_id"]: (event, payload) for event, payload in terminal_events if isinstance(payload, dict)}
    for snapshot in snapshots:
        if snapshot.run_id != run_id or snapshot.producer_ref != producer:
            blocks.append("wrong_run_evidence_reference")
            continue
        if snapshot.model_config_ref != run.config_ref:
            blocks.append("request_config_reference_mismatch")
        request_item = request_by_id.get(snapshot.attempt_id)
        terminal_item = terminal_by_id.get(snapshot.attempt_id)
        if request_item is None or terminal_item is None:
            blocks.append("attempt_occurrence_missing")
            continue
        request_event, request = request_item
        terminal_event, terminal = terminal_item
        if (
            request_event.call_id != snapshot.logical_call_id
            or terminal_event.call_id != snapshot.logical_call_id
            or request.get("logical_call_id") != snapshot.logical_call_id
            or terminal.get("logical_call_id") != snapshot.logical_call_id
        ):
            blocks.append("attempt_logical_call_mismatch")
        for name, suffix, ref in (
            ("before_body_ref", "before", snapshot.before_body_ref),
            ("prepared_body_ref", "prepared", snapshot.prepared_body_ref),
            ("sent_body_ref", "sent", snapshot.sent_body_ref),
        ):
            if ref is None or _runtime_ref(root, run_id, ref, blocks) is None:
                blocks.append("request_evidence_missing")
                continue
            if ref.locator != f"/attempts/{snapshot.attempt_id}/{suffix}":
                blocks.append("request_occurrence_mismatch")
            if request.get(name) != ref.model_dump():
                blocks.append("request_send_boundary_mismatch")
        sent = _runtime_ref(root, run_id, snapshot.sent_body_ref, blocks) if snapshot.sent_body_ref else None
        try:
            sent_messages = json.loads(sent).get("messages") if sent else None
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            sent_messages = None
        if snapshot.ordered_blocks and (not isinstance(sent_messages, list) or len(snapshot.ordered_blocks) != len(sent_messages)):
            blocks.append("request_context_mapping_mismatch")
        elif snapshot.ordered_blocks:
            try:
                build_view(
                    run_id=run_id,
                    cutoff_seq=snapshot.cutoff_seq,
                    request_draft_hash=snapshot.before_body_ref.blob_hash,
                    blocks=snapshot.ordered_blocks,
                    file_comparisons=[],
                    events=events,
                    producer_ref=producer,
                    view_id=f"audit:{snapshot.id}",
                )
            except VisibilityViolation as error:
                blocks.append(f"decision_visibility_{error.code}")
            for index, block in enumerate(snapshot.ordered_blocks):
                message = sent_messages[index]
                if (
                    block.request_id != snapshot.id
                    or block.occurrence_id != f"{snapshot.id}:block:{index}"
                    or block.body_pointer != f"/messages/{index}/content"
                    or not isinstance(message, dict)
                    or block.role != message.get("role")
                    or not isinstance(message.get("content"), str)
                    or block.content_hash != hashlib.sha256(message["content"].encode()).hexdigest()
                ):
                    blocks.append("request_context_mapping_mismatch")
                if isinstance(message, dict):
                    _audit_context_block(root, run, block, message, events, payloads, blocks)
        inventory = physical.get(snapshot.attempt_id)
        entered = inventory.get("entered") if inventory is not None else None
        terminal_inventory = inventory.get("terminal") if inventory is not None else None
        if entered is not None and entered.sent_body_ref != snapshot.sent_body_ref:
            blocks.append("physical_attempt_sent_mismatch")
        _audit_terminal_attempt(
            root,
            run_id,
            snapshot,
            terminal_event,
            terminal,
            terminal_inventory,
            blocks,
        )


def _physical_attempt_index(
    attempts: list[PhysicalAttempt],
    run_id: str,
    producer: EvidenceRef,
    root: Path,
    blocks: list[str],
) -> dict[str, dict[str, PhysicalAttempt]]:
    groups: dict[str, dict[str, PhysicalAttempt]] = {}
    counts: Counter[tuple[str, str]] = Counter()
    for attempt in attempts:
        counts[(attempt.attempt_id, attempt.phase)] += 1
        if (
            attempt.run_id != run_id
            or attempt.producer_ref != producer
            or attempt.id != f"physical-attempt:{attempt.attempt_id}:{attempt.phase}"
            or attempt.sent_body_ref.locator != f"/attempts/{attempt.attempt_id}/sent"
            or _runtime_ref(root, run_id, attempt.sent_body_ref, blocks) is None
        ):
            blocks.append("physical_attempt_identity_mismatch")
        groups.setdefault(attempt.attempt_id, {})[attempt.phase] = attempt
    if any(count != 1 for count in counts.values()):
        blocks.append("duplicate_physical_attempt")
    for phases in groups.values():
        if set(phases) != {"entered", "terminal"}:
            blocks.append("physical_attempt_terminal_missing")
            continue
        if phases["entered"].sent_body_ref != phases["terminal"].sent_body_ref:
            blocks.append("physical_attempt_sent_mismatch")
    return groups


def _audit_terminal_attempt(
    root: Path,
    run_id: str,
    snapshot: RequestSnapshot,
    event: Event,
    terminal: dict[str, Any],
    physical: PhysicalAttempt | None,
    blocks: list[str],
) -> None:
    raw_response, failure = terminal.get("raw_response_ref"), terminal.get("failure_ref")
    if event.kind == "provider_failure":
        if physical is None or physical.terminal_state != "transport_exception":
            blocks.append("physical_attempt_terminal_mismatch")
        if raw_response is not None or not isinstance(failure, dict):
            blocks.append("transport_failure_evidence_missing")
        else:
            try:
                failure_ref = EvidenceRef.model_validate(failure)
            except ValidationError:
                blocks.append("malformed_persisted_runtime_evidence")
            else:
                _runtime_ref(root, run_id, failure_ref, blocks)
                if failure_ref.locator != f"/attempts/{snapshot.attempt_id}/transport-failure":
                    blocks.append("transport_failure_identity_mismatch")
                if physical is not None and physical.failure_ref != failure_ref:
                    blocks.append("physical_attempt_terminal_mismatch")
        if terminal.get("raw_usage_ref") is not None or terminal.get("provider_request_id") is not None:
            blocks.append("transport_failure_semantics_mismatch")
        try:
            usage = Fact[dict].model_validate(terminal.get("usage"))
        except ValidationError:
            blocks.append("malformed_persisted_runtime_evidence")
        else:
            if (
                usage.status != "unknown"
                or usage.value is not None
                or usage.reason != "transport_exception_before_response"
                or usage.refs
            ):
                blocks.append("transport_failure_semantics_mismatch")
        return
    if not isinstance(raw_response, dict) or failure is not None:
        blocks.append("provider_attempt_missing_event")
        return
    try:
        response_ref = EvidenceRef.model_validate(raw_response)
    except ValidationError:
        blocks.append("malformed_persisted_runtime_evidence")
        return
    response_bytes = _runtime_ref(root, run_id, response_ref, blocks)
    if response_bytes is None:
        return
    if response_ref.locator != f"/attempts/{snapshot.attempt_id}/response":
        blocks.append("provider_response_identity_mismatch")
    if (
        physical is None
        or physical.terminal_state != "response_observed"
        or physical.raw_response_ref != response_ref
    ):
        blocks.append("physical_attempt_terminal_mismatch")
    try:
        response_json = json.loads(response_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        response_json = None
    _audit_usage(response_json, response_ref, terminal, blocks)


def _audit_usage(response_json: Any, response_ref: EvidenceRef, terminal: dict[str, Any], blocks: list[str]) -> None:
    try:
        usage = Fact[dict].model_validate(terminal.get("usage"))
    except ValidationError:
        blocks.append("malformed_persisted_runtime_evidence")
        return
    raw_usage = terminal.get("raw_usage_ref")
    observed_usage = isinstance(response_json, dict) and isinstance(response_json.get("usage"), dict)
    if not observed_usage:
        if (
            usage.status != "unknown"
            or usage.value is not None
            or usage.reason != "provider_did_not_report_usage"
            or usage.refs
            or raw_usage is not None
        ):
            blocks.append("provider_usage_invented")
        return
    if not isinstance(raw_usage, dict):
        blocks.append("provider_usage_not_observed")
        return
    try:
        usage_ref = EvidenceRef.model_validate(raw_usage)
    except ValidationError:
        blocks.append("malformed_persisted_runtime_evidence")
        return
    expected_ref = response_ref.model_copy(update={"locator": "/usage"})
    if usage_ref != expected_ref or usage.refs != [expected_ref] or usage.status != "observed":
        blocks.append("provider_usage_reference_mismatch")
    if usage.value != response_json["usage"]:
        blocks.append("provider_usage_value_mismatch")


def _audit_file_bindings(
    root: Path,
    run_id: str,
    bindings: list[FileBinding],
    events: list[Event],
    payloads: dict[int, Any],
    final: RepositoryState,
    blocks: list[str],
) -> None:
    starts = [(event, payloads.get(event.event_seq)) for event in events if event.kind == "tool_start"]
    finishes = [(event, payloads.get(event.event_seq)) for event in events if event.kind == "tool_finish"]
    start_ids = [event.call_id for event, _ in starts]
    finish_ids = [event.call_id for event, _ in finishes]
    if None in start_ids or None in finish_ids or Counter(start_ids) != Counter(finish_ids):
        blocks.append("incomplete_tool_call")
    if any(count != 1 for count in Counter(start_ids).values()) or any(count != 1 for count in Counter(finish_ids).values()):
        blocks.append("duplicate_tool_occurrence")
    finish_by_id = {event.id: (event, payload) for event, payload in finishes}
    if len({binding.read_event_id for binding in bindings}) != len(bindings):
        blocks.append("file_binding_occurrence_duplicate")
    for binding in bindings:
        item = finish_by_id.get(binding.read_event_id)
        if item is None:
            blocks.append("file_binding_without_closed_tool")
            continue
        event, result = item
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
        if ref.locator != f"/tools/{event.call_id}/body":
            blocks.append("file_binding_occurrence_mismatch")
        if binding.observed_seq != event.event_seq or binding.observed_seq != event.available_seq:
            blocks.append("file_binding_sequence_mismatch")
        if hashlib.sha256(raw).hexdigest() != binding.file_sha256 or result.get("sha256") != binding.file_sha256:
            blocks.append("file_binding_bytes_mismatch")
        if result.get("path") != binding.repo_relative_path or binding.observed_seq < 0:
            blocks.append("file_binding_identity_mismatch")
    if final.files != bindings:
        blocks.append("final_state_file_bindings_mismatch")


def _audit_decision_views(
    root: Path,
    run_id: str,
    run: Run,
    producer: EvidenceRef,
    events: list[Event],
    payloads: dict[int, Any],
    snapshots: list[RequestSnapshot],
    blocks: list[str],
) -> None:
    directory = root / "runs" / run_id / "decision_views"
    if not directory.exists():
        return
    try:
        paths = sorted(directory.glob("*.json"))
        views = [DecisionView.model_validate_json(path.read_text()) for path in paths]
    except (OSError, UnicodeDecodeError, ValidationError, ValueError):
        blocks.append("malformed_persisted_decision_evidence")
        return
    for path, view in zip(paths, views, strict=True):
        if path.stem != view.id or view.run_id != run_id or view.producer_ref != producer:
            blocks.append("decision_view_identity_mismatch")
        matching_snapshots = [
            snapshot
            for snapshot in snapshots
            if snapshot.ordered_blocks == view.blocks
            and snapshot.cutoff_seq == view.cutoff_seq
            and snapshot.before_body_ref.blob_hash == view.request_draft_hash
        ]
        if len(matching_snapshots) != 1:
            blocks.append("decision_view_request_mismatch")
        try:
            rebuilt = build_view(
                run_id=run_id,
                cutoff_seq=view.cutoff_seq,
                request_draft_hash=view.request_draft_hash,
                blocks=view.blocks,
                file_comparisons=view.file_comparisons,
                events=events,
                producer_ref=producer,
                policy_version=view.policy_version,
                view_id=view.id,
            )
        except VisibilityViolation as error:
            blocks.append(f"decision_visibility_{error.code}")
            continue
        if rebuilt != view:
            blocks.append("decision_view_derivation_mismatch")
        for comparison in view.file_comparisons:
            matching_blocks = [
                block
                for block in view.blocks
                if block.file_binding is not None
                and block.provenance_ref is not None
                and block.provenance_ref == comparison.binding_ref
            ]
            if len(matching_blocks) != 1:
                blocks.append("file_comparison_binding_mismatch")
                continue
            binding = matching_blocks[0].file_binding
            assert binding is not None
            state_checks = [
                event
                for event in events
                if event.kind == "state_check"
                and event.run_id == run_id
                and event.available_seq == comparison.checked_seq
                and event.call_id == binding.read_event_id
            ]
            if len(state_checks) != 1:
                blocks.append("file_comparison_state_check_mismatch")
                continue
            state_check = state_checks[0]
            state_payload = payloads.get(state_check.event_seq)
            expected_payload = {
                "binding_ref": comparison.binding_ref.model_dump(),
                "repo_relative_path": binding.repo_relative_path,
                "historical_file_sha256": binding.file_sha256,
                "current_file_ref": (
                    comparison.current_file_ref.model_dump()
                    if comparison.current_file_ref is not None
                    else None
                ),
                "current_file_sha256": comparison.current_file_sha256,
                "status": comparison.status,
                "reason": comparison.reason,
            }
            if state_payload != expected_payload:
                blocks.append("file_comparison_state_check_mismatch")
            historical = _load_ref_blob(root, comparison.binding_ref, blocks)
            if historical is None or hashlib.sha256(historical).hexdigest() != binding.file_sha256:
                blocks.append("file_comparison_binding_mismatch")
            if comparison.status == "unknown":
                continue
            assert comparison.current_file_ref is not None
            current = _load_ref_blob(root, comparison.current_file_ref, blocks)
            expected_locator = (
                f"/state-checks/{comparison.checked_seq}/{binding.repo_relative_path}"
            )
            if (
                current is None
                or comparison.current_file_ref.source_id != "acr_runtime"
                or comparison.current_file_ref.trajectory_key != run_id
                or comparison.current_file_ref.locator != expected_locator
                or len(comparison.current_file_ref.labels) != 1
                or comparison.current_file_ref.labels[0].scope != "runtime"
                or comparison.current_file_ref.labels[0].run_id != run_id
                or comparison.current_file_ref.labels[0].available_seq != comparison.checked_seq
                or comparison.current_file_ref.labels[0].taints
                or comparison.current_file_ref.labels != _canonical_event_labels(state_check)
                or hashlib.sha256(current).hexdigest() != comparison.current_file_sha256
            ):
                blocks.append("file_comparison_evidence_mismatch")
                continue
            expected_status = (
                "same" if comparison.current_file_sha256 == binding.file_sha256 else "changed"
            )
            if comparison.status != expected_status:
                blocks.append("file_comparison_status_mismatch")


def audit_run(root: Path, run_id: str) -> AuditResult:
    """Fail closed over persisted M2 artifacts; it never executes a runtime."""

    blocks: list[str] = []
    try:
        _audit_runtime(root, run_id, blocks)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        blocks.append("malformed_persisted_runtime_evidence")
    return AuditResult("BLOCK" if blocks else "PASS", tuple(sorted(set(blocks))))


def audit_evaluation(root: Path, run_id: str, private_spec_ref: str) -> AuditResult:
    """Audit persisted evaluator artifacts without invoking evaluation again."""

    blocks: list[str] = []
    try:
        run = Run.model_validate(load_run_json(root, run_id, "run.json"))
        result = EvaluationResult.model_validate_json(
            (root / "evaluations" / run_id / "evaluation_result.json").read_text()
        )
        private_bytes = Path(private_spec_ref).read_bytes()
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValidationError, ValueError):
        return AuditResult("BLOCK", ("malformed_persisted_evaluation_evidence",))
    if run.sealed_artifact_hash is None or result.run_id != run.id or result.submitted_artifact_hash != run.sealed_artifact_hash:
        blocks.append("evaluation_run_binding_mismatch")
    _audit_evaluation_producer(root, run_id, result, private_bytes, blocks)
    raw = _load_ref_blob(root, result.raw_result_ref, blocks)
    if (
        result.raw_result_ref.source_id != "acr_evaluator"
        or result.raw_result_ref.trajectory_key != run_id
        or result.raw_result_ref.locator != "/evaluation/result"
        or not any(label.scope == "evaluator" and label.run_id == run_id for label in result.raw_result_ref.labels)
    ):
        blocks.append("evaluation_raw_reference_mismatch")
    try:
        record = json.loads(raw) if raw is not None else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        record = None
    if result.status == "completed":
        for field in ("patch_valid", "tests_executed", "passed", "failed", "resolved"):
            fact = getattr(result, field)
            if (
                not isinstance(record, dict)
                or record.get("status") != "completed"
                or fact.status != "observed"
                or fact.refs != [result.raw_result_ref]
                or fact.value != record.get(field)
            ):
                blocks.append("evaluation_fact_mismatch")
    try:
        paths = list((root / "runs" / run_id).rglob("*")) + list((root / "blobs").glob("*"))
        for path in paths:
            if path.is_file() and private_bytes in path.read_bytes():
                blocks.append("evaluator_private_data_leakage")
                break
    except OSError:
        blocks.append("malformed_persisted_evaluation_evidence")
    return AuditResult("BLOCK" if blocks else "PASS", tuple(sorted(set(blocks))))


def audit_pair(root: Path, pair_id: str, private_spec_ref: str) -> AuditResult:
    """Audit a persisted noop A/A pair without re-running either arm."""

    blocks: list[str] = []
    try:
        pair = Pair.model_validate(load_pair_json(root, pair_id, "pair.json"))
        manifest_raw = (root / "pairs" / pair_id / "pair_manifest.json").read_bytes()
        manifest_ref = EvidenceRef.model_validate_json(
            (root / "pairs" / pair_id / "producer_ref.json").read_text()
        )
        producer_file = (root / "pairs" / pair_id / "producer_manifest.json").read_bytes()
        producer_blob = _load_ref_blob(root, manifest_ref, blocks)
        manifest = json.loads(manifest_raw)
        run_a = Run.model_validate(load_run_json(root, pair.baseline_run_id, "run.json"))
        run_b = Run.model_validate(load_run_json(root, pair.treatment_run_id, "run.json"))
        initial_a = RepositoryState.model_validate(load_run_json(root, pair.baseline_run_id, "initial_state.json"))
        initial_b = RepositoryState.model_validate(load_run_json(root, pair.treatment_run_id, "initial_state.json"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        return AuditResult("BLOCK", ("malformed_persisted_pair_evidence",))
    if pair.id != pair_id or pair.mode != "from_scratch" or pair.status != "completed":
        blocks.append("pair_identity_mismatch")
    if pair.baseline_run_id == pair.treatment_run_id:
        blocks.append("pair_same_run")
    if pair.execution_order not in {"AB", "BA"}:
        blocks.append("pair_execution_order_mismatch")
    if hashlib.sha256(manifest_raw).hexdigest() != pair.manifest_hash:
        blocks.append("pair_manifest_hash_mismatch")
    pair_manifest_blob = _load_ref_blob(root, pair.provenance_ref, blocks) if pair.provenance_ref else None
    if (
        pair.provenance_ref is None
        or pair.provenance_ref.blob_hash != hashlib.sha256(manifest_raw).hexdigest()
        or pair.provenance_ref.source_id != "acr_pair_manifest"
        or pair.provenance_ref.trajectory_key != pair_id
        or pair.provenance_ref.locator != "/pair-manifest"
        or pair_manifest_blob != manifest_raw
    ):
        blocks.append("pair_manifest_reference_mismatch")
    if (
        manifest_ref.source_id != "acr_pair_producer"
        or manifest_ref.trajectory_key != pair_id
        or manifest_ref.locator != "/producer-manifest"
        or pair.producer_ref != manifest_ref
        or producer_blob != producer_file
    ):
        blocks.append("pair_producer_mismatch")
    try:
        producer = json.loads(producer_blob) if producer_blob is not None else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        producer = None
    if (
        not isinstance(producer, dict)
        or producer.get("producer_kind") != "acr_noop_pair_harness"
        or producer.get("schema_version") != "1.0"
        or producer.get("runtime_version") != "m3_noop_pair_v1"
        or not isinstance(producer.get("code_revision"), str)
        or len(producer["code_revision"]) != 40
    ):
        blocks.append("pair_producer_mismatch")
    if not isinstance(manifest, dict):
        return AuditResult("BLOCK", tuple(sorted(set(blocks + ["malformed_persisted_pair_evidence"]))))
    _audit_pair_manifest(root, pair, manifest, run_a, run_b, initial_a, initial_b, blocks)
    if audit_run(root, pair.baseline_run_id).status != "PASS" or audit_run(root, pair.treatment_run_id).status != "PASS":
        blocks.append("pair_run_audit_block")
    if audit_evaluation(root, pair.baseline_run_id, private_spec_ref).status != "PASS" or audit_evaluation(root, pair.treatment_run_id, private_spec_ref).status != "PASS":
        blocks.append("pair_evaluation_audit_block")
    return AuditResult("BLOCK" if blocks else "PASS", tuple(sorted(set(blocks))))


def _authoritative_run_stop(
    root: Path, run_id: str, blocks: list[str]
) -> datetime | None:
    """Return the sole completed final run-stop occurrence from persisted events."""

    events = _load_jsonl_models(root / "runs" / run_id / "events.jsonl", Event, blocks)
    if events is None:
        blocks.append("pair_phase_order_mismatch")
        return None
    stops = [event for event in events if event.kind == "run_stop"]
    if (
        len(stops) != 1
        or events[-1] != stops[0]
        or stops[0].run_id != run_id
        or stops[0].end is None
        or stops[0].end.tzinfo is None
        or stops[0].available_seq != stops[0].event_seq
    ):
        blocks.append("pair_phase_order_mismatch")
        return None
    return stops[0].end


def _audit_pair_manifest(
    root: Path,
    pair: Pair,
    manifest: dict[str, Any],
    run_a: Run,
    run_b: Run,
    initial_a: RepositoryState,
    initial_b: RepositoryState,
    blocks: list[str],
) -> None:
    """Validate pre-frozen arm conditions against persisted run evidence."""

    required = (
        "pair_id", "replicate_id", "task_id", "baseline_run_id", "treatment_run_id",
        "execution_order", "mode", "source_tree_hash", "semantic_config_A", "semantic_config_B",
        "semantic_config_hash_A", "semantic_config_hash_B", "workspace_identity_A", "workspace_identity_B",
    )
    if any(key not in manifest for key in required):
        blocks.append("pair_manifest_incomplete")
        return
    if (
        manifest["pair_id"] != pair.id
        or manifest["replicate_id"] != pair.replicate_id
        or manifest["task_id"] != pair.task_id
        or manifest["baseline_run_id"] != pair.baseline_run_id
        or manifest["treatment_run_id"] != pair.treatment_run_id
        or manifest["execution_order"] != pair.execution_order
        or manifest["mode"] != pair.mode
    ):
        blocks.append("pair_manifest_run_binding_mismatch")
    config_a, config_b = manifest["semantic_config_A"], manifest["semantic_config_B"]
    if not isinstance(config_a, dict) or not isinstance(config_b, dict):
        blocks.append("pair_semantic_config_mismatch")
        return
    canonical_a = hashlib.sha256(json.dumps(config_a, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    canonical_b = hashlib.sha256(json.dumps(config_b, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if (
        config_a != config_b
        or manifest["semantic_config_hash_A"] != canonical_a
        or manifest["semantic_config_hash_B"] != canonical_b
        or canonical_a != canonical_b
        or config_a.get("intervention") != "noop"
        or config_b.get("intervention") != "noop"
    ):
        blocks.append("pair_semantic_config_mismatch")
    if pair.preflight_result.status != "observed" or pair.preflight_result.value is not True or pair.preflight_result.refs != [pair.provenance_ref]:
        blocks.append("pair_preflight_evidence_mismatch")
    if run_a.task_id != pair.task_id or run_b.task_id != pair.task_id:
        blocks.append("pair_task_identity_mismatch")
    source_hash = manifest["source_tree_hash"]
    if (
        initial_a.initial_tree_hash != source_hash
        or initial_b.initial_tree_hash != source_hash
        or config_a.get("task_source_tree_hash") != source_hash
        or config_b.get("task_source_tree_hash") != source_hash
    ):
        blocks.append("pair_initial_state_mismatch")
    if (
        run_a.capabilities.get("workspace_identity") != manifest["workspace_identity_A"]
        or run_b.capabilities.get("workspace_identity") != manifest["workspace_identity_B"]
        or manifest["workspace_identity_A"] == manifest["workspace_identity_B"]
    ):
        blocks.append("pair_workspace_isolation_mismatch")
    if run_a.config_ref.blob_hash != run_b.config_ref.blob_hash:
        blocks.append("pair_runtime_config_mismatch")
        return
    try:
        config_a_raw = _runtime_ref(root, run_a.id, run_a.config_ref, blocks)
        config_b_raw = _runtime_ref(root, run_b.id, run_b.config_ref, blocks)
        actual_a = json.loads(config_a_raw) if config_a_raw else None
        actual_b = json.loads(config_b_raw) if config_b_raw else None
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        blocks.append("pair_runtime_config_mismatch")
        return
    semantic_fields = ("provider", "model", "base_url", "intervention", "cache_isolation")
    for key in semantic_fields:
        if actual_a is None or actual_b is None or actual_a.get(key) != config_a.get(key) or actual_b.get(key) != config_b.get(key):
            blocks.append("pair_actual_execution_binding_mismatch")
    budget_a = actual_a.get("budget") if isinstance(actual_a, dict) else None
    budget_b = actual_b.get("budget") if isinstance(actual_b, dict) else None
    semantic_budget = config_a.get("attempt_budget")
    expected_attempts = (
        semantic_budget.get("hard_max_physical_attempts")
        if isinstance(semantic_budget, dict)
        else None
    )
    if (
        not isinstance(budget_a, dict)
        or not isinstance(budget_b, dict)
        or budget_a.get("hard_max_physical_attempts") != expected_attempts
        or budget_b.get("hard_max_physical_attempts") != expected_attempts
    ):
        blocks.append("pair_actual_execution_binding_mismatch")
    for run in (run_a, run_b):
        producer = _load_runtime_producer(root, run.id, run, blocks)
        raw = _runtime_ref(root, run.id, producer, blocks)
        try:
            producer_manifest = json.loads(raw) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            producer_manifest = None
        if not isinstance(producer_manifest, dict) or producer_manifest.get("code_revision") != config_a.get("runtime_code_revision"):
            blocks.append("pair_runtime_revision_mismatch")
    evaluation_starts: list[datetime] = []
    for run in (run_a, run_b):
        try:
            result = EvaluationResult.model_validate_json((root / "evaluations" / run.id / "evaluation_result.json").read_text())
            eproducer = json.loads((root / "evaluations" / run.id / "producer_manifest.json").read_text())
        except (OSError, ValidationError, json.JSONDecodeError):
            blocks.append("pair_evaluator_binding_mismatch")
            continue
        if not isinstance(eproducer, dict):
            blocks.extend(("pair_evaluator_binding_mismatch", "pair_phase_order_mismatch"))
            continue
        if result.evaluator_revision != config_a.get("evaluator_version") or eproducer.get("private_spec_sha256") != config_a.get("private_spec_sha256"):
            blocks.append("pair_evaluator_binding_mismatch")
        try:
            started = datetime.fromisoformat(eproducer["evaluation_started_at"])
            if started.tzinfo is None:
                raise ValueError("evaluation start has no timezone")
            evaluation_starts.append(started)
        except (KeyError, TypeError, ValueError):
            blocks.append("pair_phase_order_mismatch")
    run_stops = (
        _authoritative_run_stop(root, run_a.id, blocks),
        _authoritative_run_stop(root, run_b.id, blocks),
    )
    valid_run_stops = [stop for stop in run_stops if stop is not None]
    if (
        len(valid_run_stops) != 2
        or len(evaluation_starts) != 2
        or any(started < max(valid_run_stops) for started in evaluation_starts)
    ):
        blocks.append("pair_phase_order_mismatch")


def _audit_evaluation_producer(
    root: Path,
    run_id: str,
    result: EvaluationResult,
    private_bytes: bytes,
    blocks: list[str],
) -> None:
    """Close evaluator result, producer artifact, and private-spec identity."""

    try:
        persisted_ref = EvidenceRef.model_validate_json(
            (root / "evaluations" / run_id / "producer_ref.json").read_text()
        )
        persisted_manifest = (root / "evaluations" / run_id / "producer_manifest.json").read_bytes()
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValidationError, ValueError):
        blocks.append("malformed_persisted_evaluation_evidence")
        return
    producer_blob = _load_ref_blob(root, persisted_ref, blocks)
    if (
        result.producer_ref != persisted_ref
        or persisted_ref.source_id != "acr_evaluator"
        or persisted_ref.trajectory_key != run_id
        or persisted_ref.locator != "/evaluation/producer-manifest"
        or not any(
            label.scope == "evaluator" and label.run_id == run_id
            for label in persisted_ref.labels
        )
        or producer_blob != persisted_manifest
    ):
        blocks.append("evaluation_producer_mismatch")
    if producer_blob is None:
        return
    try:
        manifest = json.loads(producer_blob)
    except (UnicodeDecodeError, json.JSONDecodeError):
        blocks.append("malformed_persisted_evaluation_evidence")
        return
    required = (
        "producer_kind",
        "schema_version",
        "evaluator_version",
        "code_revision",
        "private_spec_sha256",
        "evaluation_started_at",
    )
    valid_code_revision = (
        isinstance(manifest, dict)
        and isinstance(manifest.get("code_revision"), str)
        and len(manifest["code_revision"]) == 40
        and all(char in "0123456789abcdef" for char in manifest["code_revision"])
    )
    valid_spec_hash = (
        isinstance(manifest, dict)
        and isinstance(manifest.get("private_spec_sha256"), str)
        and len(manifest["private_spec_sha256"]) == 64
        and all(char in "0123456789abcdef" for char in manifest["private_spec_sha256"])
    )
    try:
        evaluation_started_at = datetime.fromisoformat(manifest["evaluation_started_at"])
        valid_evaluation_start = evaluation_started_at.tzinfo is not None
    except (KeyError, TypeError, ValueError):
        valid_evaluation_start = False
    if (
        not isinstance(manifest, dict)
        or any(not isinstance(manifest.get(key), str) or not manifest[key].strip() for key in required)
        or manifest.get("producer_kind") != "acr_local_add_evaluator"
        or manifest.get("schema_version") != "1.0"
        or manifest.get("evaluator_version") != "local_add_evaluator_v1"
        or not valid_code_revision
        or not valid_spec_hash
        or not valid_evaluation_start
        or result.evaluator_revision != manifest.get("evaluator_version")
    ):
        blocks.append("evaluation_producer_mismatch")
    if not valid_spec_hash or manifest.get("private_spec_sha256") != hashlib.sha256(private_bytes).hexdigest():
        blocks.append("evaluation_private_spec_mismatch")
