"""Fail-closed audit of persisted M1 artifacts only."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from acr.adapters.legacy import ADAPTER_VERSION, parse_document
from acr.contracts import (
    EvaluationResult,
    Event,
    EvidenceRef,
    Fact,
    FileBinding,
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
        if final.tree_ref != run.sealed_artifact_ref:
            blocks.append("final_state_sealed_artifact_mismatch")


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
    if (
        not isinstance(manifest, dict)
        or any(not isinstance(manifest.get(key), str) or not manifest[key].strip() for key in required)
        or manifest.get("producer_kind") != "acr_local_add_evaluator"
        or manifest.get("schema_version") != "1.0"
        or manifest.get("evaluator_version") != "local_add_evaluator_v1"
        or not valid_code_revision
        or not valid_spec_hash
        or result.evaluator_revision != manifest.get("evaluator_version")
    ):
        blocks.append("evaluation_producer_mismatch")
    if not valid_spec_hash or manifest.get("private_spec_sha256") != hashlib.sha256(private_bytes).hexdigest():
        blocks.append("evaluation_private_spec_mismatch")
