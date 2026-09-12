"""F1 product entry point, Claude hook handler, and session integrity audit."""

from __future__ import annotations

import fcntl
import hashlib
import json
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from acr.adapters.claude_hooks import (
    TOOL_HOOK_EVENTS,
    is_exact_verifier_invocation,
    sanitize_claude_hook_payload,
)
from acr.contracts import EvidenceRef, Fact, InformationLabel, Provenance
from acr.demo_raw import demo_raw_session_path, initialize_demo_raw_session
from acr.forensics.checkpoint import CheckpointCaptureError, capture_workspace_checkpoint
from acr.forensics.config import load_project_config
from acr.forensics.store import ForensicsEvidenceStore, canonical_json_bytes, sha256_bytes
from acr.forensics_contracts import (
    AgentEvent,
    OperationIdentity,
    OrderingEvidence,
    VerificationReceipt,
    WorkspaceCheckpoint,
    canonical_captured_state_manifest_bytes,
)

MAX_HOOK_INPUT_BYTES = 1024 * 1024
_HOOK_EVENTS = ("SessionStart", "PreToolUse", "PostToolUse", "PostToolUseFailure", "SessionEnd")
_VALIDATED_CLAUDE_VERSION = "2.1.144 (Claude Code)"
_VALIDATED_PLATFORM_FAMILY = "Ubuntu/WSL2"


class SessionIntegrityError(RuntimeError):
    """Production evidence failed its required local integrity boundary."""


def _platform_family() -> str:
    release = platform.release().lower()
    try:
        os_release = Path("/etc/os-release").read_text()
    except OSError:
        os_release = ""
    if "microsoft" in release and "ID=ubuntu\n" in os_release:
        return "Ubuntu/WSL2"
    return "unvalidated"


def _require_validated_runtime_profile(metadata: dict[str, Any]) -> None:
    if (
        metadata.get("claude_version") != _VALIDATED_CLAUDE_VERSION
        or metadata.get("platform_family") != _VALIDATED_PLATFORM_FAMILY
    ):
        raise SessionIntegrityError(
            "unvalidated Claude runtime profile: trusted v0.1 evidence is disabled"
        )


def _trusted_terminal_result(observation: dict[str, Any]) -> tuple[bool, int] | None:
    kind = observation.get("termination_kind")
    exit_code = observation.get("exit_code")
    if kind == "success" and exit_code == 0:
        return True, 0
    if (
        kind == "exited"
        and isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
        and exit_code != 0
    ):
        return False, exit_code
    return None


def _repo_identity(repo_root: Path) -> str:
    return hashlib.sha256(str(repo_root.resolve()).encode()).hexdigest()


def _producer_and_config_refs(metadata: dict[str, Any]) -> tuple[EvidenceRef, EvidenceRef]:
    try:
        return (
            EvidenceRef.model_validate(metadata["producer_ref"]),
            EvidenceRef.model_validate(metadata["config_ref"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SessionIntegrityError("session evidence references are malformed") from error


def build_claude_settings(command: str) -> dict[str, Any]:
    hooks: dict[str, list[dict[str, Any]]] = {}
    for event_name in _HOOK_EVENTS:
        handler: dict[str, Any] = {
            "hooks": [{"command": command, "timeout": 120, "type": "command"}]
        }
        if event_name in TOOL_HOOK_EVENTS:
            handler["matcher"] = "*"
        hooks[event_name] = [handler]
    return {"hooks": hooks}


def _active_session_lock(repo_root: Path):
    lock_root = Path(tempfile.gettempdir()) / "acr-active-sessions"
    lock_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = lock_root / f"{_repo_identity(repo_root)}.lock"
    handle = lock_path.open("a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise SessionIntegrityError(
            "another Agent Forensics session is active for this worktree"
        ) from None
    return handle


def _git_top_level(repo_root: Path) -> Path:
    try:
        value = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise SessionIntegrityError("current directory is not a usable Git repository") from error
    return Path(value).resolve()


def run_claude_session(
    *,
    repo_root: Path,
    config_path: Path,
    data_root_override: Path | None,
    claude_args: list[str],
    demo_raw_capture: bool = False,
) -> tuple[int, str, dict[str, Any] | None]:
    """Launch one real Claude session with temporary, additive hook settings."""

    repo_root = _git_top_level(repo_root.resolve())
    config = load_project_config(config_path.resolve())
    data_root = (
        data_root_override.resolve()
        if data_root_override is not None
        else (repo_root / config.data_root).resolve()
    )
    git_dir = subprocess.check_output(
        ["git", "-C", str(repo_root), "rev-parse", "--absolute-git-dir"],
        text=True,
    ).strip()
    try:
        data_root.relative_to(Path(git_dir).resolve())
    except ValueError:
        pass
    else:
        raise SessionIntegrityError("evidence data_root cannot be inside the Git metadata directory")
    claude = shutil.which("claude")
    if claude is None:
        raise SessionIntegrityError("Claude Code executable is unavailable")
    try:
        claude_version = subprocess.check_output([claude, "--version"], text=True).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise SessionIntegrityError("Claude Code version could not be observed") from error
    platform_family = _platform_family()
    _require_validated_runtime_profile(
        {"claude_version": claude_version, "platform_family": platform_family}
    )

    session_id = f"session-{uuid.uuid4().hex}"
    store = ForensicsEvidenceStore(data_root, session_id)
    store.initialize_session(
        repo_identity_hash=_repo_identity(repo_root),
        verifier=config.verifier,
        selected_untracked_paths=config.selected_untracked_paths,
        max_blob_bytes=config.max_blob_bytes,
        claude_version=claude_version,
        platform_family=platform_family,
    )
    raw_session_dir = demo_raw_session_path(
        repo_root, session_id, enabled=demo_raw_capture
    )
    if raw_session_dir is not None:
        initialize_demo_raw_session(
            raw_session_dir,
            acr_session_id=session_id,
            claude_version=claude_version,
            repo_root=repo_root,
            verifier=config.verifier,
        )
    hook_parts = [
        sys.executable,
        "-m",
        "acr.cli",
        "_forensics-hook",
        "--data-root",
        str(data_root),
        "--session-id",
        session_id,
        "--repo-root",
        str(repo_root),
    ]
    if raw_session_dir is not None:
        hook_parts.extend(["--demo-raw-session-dir", str(raw_session_dir)])
    hook_command = shlex.join(hook_parts)
    active_lock = _active_session_lock(repo_root)
    try:
        with tempfile.TemporaryDirectory(prefix="acr-claude-settings-") as temporary:
            settings_path = Path(temporary) / "settings.json"
            settings_path.write_bytes(canonical_json_bytes(build_claude_settings(hook_command)))
            settings_path.chmod(0o600)
            command = [claude, "--settings", str(settings_path), *claude_args]
            result = subprocess.run(command, cwd=repo_root, check=False)
    finally:
        active_lock.close()

    issues = audit_session(data_root, session_id)
    if issues:
        raise SessionIntegrityError("session evidence audit BLOCK: " + "; ".join(issues))
    latest = _latest_receipt(store)
    return result.returncode, session_id, latest


def _event_from_observation(
    store: ForensicsEvidenceStore,
    metadata: dict[str, Any],
    observation: dict[str, Any],
) -> tuple[AgentEvent, EvidenceRef]:
    producer_ref, config_ref = _producer_and_config_refs(metadata)
    sequence = store.reserve_sequence()
    source_value = {**observation, "session_sequence": sequence}
    source_ref = store.ref_for_bytes(
        canonical_json_bytes(source_value),
        source_id="claude_hook_sanitized",
        locator=f"/hook-observations/{sequence}",
    )
    identifier = f"event-{uuid.uuid4().hex}"
    provenance_ref = store.persist_provenance(
        identifier=f"prov-{uuid.uuid4().hex}",
        producer_ref=producer_ref,
        output_object=identifier,
        input_refs=[source_ref],
        transform_name="claude_hook_to_agent_event",
        config_ref=config_ref,
    )
    operation_data = observation.get("operation")
    operation = None
    if (
        isinstance(operation_data, dict)
        and operation_data.get("occurrence_id") != "unknown"
        and operation_data.get("name") != "unknown"
    ):
        operation = OperationIdentity.model_validate(operation_data)
    event = AgentEvent(
        id=identifier,
        producer_ref=producer_ref,
        provenance_ref=provenance_ref,
        session_id=store.session_id,
        ordering=OrderingEvidence(
            sequence=Fact(value=sequence, status="observed", refs=[source_ref]),
            basis="locked_session_sequence_v1",
        ),
        timestamp=datetime.fromisoformat(observation["observed_at"]),
        event_kind=f"claude.{observation['hook_event_name']}",
        operation=operation,
        source_evidence_ref=source_ref,
        raw_evidence_ref=None,
    )
    return event, store.persist_record("events", event)


def _persist_verifier_pre_state(
    *,
    store: ForensicsEvidenceStore,
    repo_root: Path,
    metadata: dict[str, Any],
    observation: dict[str, Any],
    event: AgentEvent,
    event_ref: EvidenceRef,
) -> None:
    if event.operation is None or observation["cwd_scope"] != ".":
        raise SessionIntegrityError("exact verifier pre-event lacks root-scoped occurrence evidence")
    checkpoint, checkpoint_ref = capture_workspace_checkpoint(
        store=store,
        repo_root=repo_root,
        session_metadata=metadata,
        trigger_event_ref=event_ref,
        trigger_operation_id=event.operation.occurrence_id,
    )
    pending = {
        "checkpoint_id": checkpoint.id,
        "checkpoint_ref": checkpoint_ref.model_dump(mode="json"),
        "command": metadata["verifier"],
        "external_session_hash": observation["external_session_hash"],
        "pre_event_id": event.id,
        "pre_event_ref": event_ref.model_dump(mode="json"),
        "pre_sequence": event.ordering.sequence.value,
        "schema": "acr.verifier-correlation/0.1",
        "session_id": store.session_id,
        "started_at": observation["observed_at"],
        "tested_manifest_hash": checkpoint.captured_workspace_manifest_hash,
        "tool_use_id": event.operation.occurrence_id,
        "verifier_spec_hash": metadata["verifier_spec_hash"],
    }
    store.persist_pending(event.operation.occurrence_id, pending)


def _persist_verifier_result(
    *,
    store: ForensicsEvidenceStore,
    metadata: dict[str, Any],
    observation: dict[str, Any],
    event: AgentEvent,
    event_ref: EvidenceRef,
) -> VerificationReceipt:
    if event.operation is None or observation["cwd_scope"] != ".":
        raise SessionIntegrityError("verifier result lacks root-scoped occurrence evidence")
    terminal_result = _trusted_terminal_result(observation)
    if terminal_result is None:
        raise SessionIntegrityError("verifier terminal result is not receipt-eligible")
    pending = store.load_pending(event.operation.occurrence_id)
    expected = {
        "command": metadata["verifier"],
        "external_session_hash": observation["external_session_hash"],
        "session_id": store.session_id,
        "tool_use_id": event.operation.occurrence_id,
        "verifier_spec_hash": metadata["verifier_spec_hash"],
    }
    if any(pending.get(key) != value for key, value in expected.items()):
        raise SessionIntegrityError("verifier pre/result correlation does not match")
    try:
        checkpoint = WorkspaceCheckpoint.model_validate_json(
            store.read_record("checkpoints", pending["checkpoint_id"])
        )
        checkpoint_ref = EvidenceRef.model_validate(pending["checkpoint_ref"])
        pre_event_ref = EvidenceRef.model_validate(pending["pre_event_ref"])
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise SessionIntegrityError("verifier pre-state evidence cannot be resolved") from error
    if (
        checkpoint.session_id != store.session_id
        or checkpoint.captured_workspace_manifest_hash != pending.get("tested_manifest_hash")
        or sha256_bytes(store.read_record("checkpoints", checkpoint.id)) != checkpoint_ref.blob_hash
    ):
        raise SessionIntegrityError("verifier checkpoint binding is invalid")

    receipt_id = "vr-" + sha256_bytes(
        f"{store.session_id}\0{event.operation.occurrence_id}".encode()
    )[:40]
    existing = store.record_path("receipts", receipt_id)
    if existing.exists():
        return VerificationReceipt.model_validate_json(existing.read_text())
    producer_ref, config_ref = _producer_and_config_refs(metadata)
    provenance_ref = store.persist_provenance(
        identifier=f"prov-{uuid.uuid4().hex}",
        producer_ref=producer_ref,
        output_object=receipt_id,
        input_refs=[pre_event_ref, checkpoint_ref, event_ref, config_ref],
        transform_name="bind_exact_verifier_result",
        config_ref=config_ref,
    )
    passed, exit_code = terminal_result
    receipt = VerificationReceipt(
        id=receipt_id,
        producer_ref=producer_ref,
        provenance_ref=provenance_ref,
        session_id=store.session_id,
        verifier_id=f"exact-command-{metadata['verifier_spec_hash'][:16]}",
        verifier_spec_hash=metadata["verifier_spec_hash"],
        verifier_config_ref=config_ref,
        pre_checkpoint_id=checkpoint.id,
        tested_captured_workspace_manifest_hash=checkpoint.captured_workspace_manifest_hash,
        command=Fact(value=metadata["verifier"], status="observed", refs=[config_ref]),
        passed=Fact(value=passed, status="observed", refs=[event_ref]),
        exit_code=Fact(value=exit_code, status="observed", refs=[event_ref]),
        started_at=Fact(
            value=datetime.fromisoformat(pending["started_at"]),
            status="observed",
            refs=[pre_event_ref],
        ),
        finished_at=Fact(
            value=event.timestamp,
            status="observed",
            refs=[event_ref],
        ),
        ordering=OrderingEvidence(
            sequence=Fact(
                value=store.reserve_sequence(),
                status="observed",
                refs=[event_ref],
            ),
            basis="locked_session_sequence_v1",
        ),
        operation=event.operation,
        output_capture="not_persisted_by_policy",
    )
    store.persist_record("receipts", receipt)
    return receipt


def handle_claude_hook(
    *,
    raw_input: bytes,
    data_root: Path,
    session_id: str,
    repo_root: Path,
) -> int:
    """Handle one command hook; block exact verification when pre-capture fails."""

    store = ForensicsEvidenceStore(data_root, session_id)
    exact_pre = False
    try:
        if not raw_input or len(raw_input) > MAX_HOOK_INPUT_BYTES:
            store.persist_anomaly(
                "hook_input_empty_or_oversized_not_persisted",
                details={"input_byte_count": len(raw_input)},
            )
            return 0
        payload = json.loads(raw_input)
        if not isinstance(payload, dict):
            raise TypeError("hook payload is not an object")
        metadata = store.load_session()
        exact = is_exact_verifier_invocation(payload, metadata["verifier"])
        exact_pre = exact and payload.get("hook_event_name") == "PreToolUse"
        _require_validated_runtime_profile(metadata)
        repo_root = repo_root.resolve()
        if _repo_identity(repo_root) != metadata["repo_identity_hash"]:
            raise SessionIntegrityError("hook repository identity does not match session")
        observation = sanitize_claude_hook_payload(payload, repo_root, metadata["verifier"])
        store.bind_external_session(observation["external_session_hash"])
        event, event_ref = _event_from_observation(store, metadata, observation)
        if exact_pre:
            _persist_verifier_pre_state(
                store=store,
                repo_root=repo_root,
                metadata=metadata,
                observation=observation,
                event=event,
                event_ref=event_ref,
            )
        elif (
            exact
            and payload.get("hook_event_name") in {"PostToolUse", "PostToolUseFailure"}
            and _trusted_terminal_result(observation) is not None
        ):
            _persist_verifier_result(
                store=store,
                metadata=metadata,
                observation=observation,
                event=event,
                event_ref=event_ref,
            )
        return 0
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        TypeError,
        ValueError,
        SessionIntegrityError,
        CheckpointCaptureError,
    ) as error:
        store.persist_anomaly(type(error).__name__)
        return 2 if exact_pre else 0


def _verify_ref(store: ForensicsEvidenceStore, ref: EvidenceRef) -> bool:
    try:
        return (
            ref.trajectory_key == store.session_id
            and sha256_bytes(store.blob_bytes(ref.blob_hash)) == ref.blob_hash
        )
    except (OSError, ValueError):
        return False


def _provenance_issue(
    store: ForensicsEvidenceStore,
    provenance_ref: EvidenceRef | None,
    *,
    producer_ref: EvidenceRef,
    output_object: str,
    required_inputs: list[EvidenceRef],
) -> str | None:
    if provenance_ref is None or not _verify_ref(store, provenance_ref):
        return "provenance evidence mismatch"
    try:
        provenance = Provenance.model_validate_json(store.blob_bytes(provenance_ref.blob_hash))
    except (ValueError, OSError):
        return "malformed provenance evidence"
    if provenance.producer_ref != producer_ref or provenance.output_object != output_object:
        return "provenance producer/output mismatch"
    identities = {item.occurrence_identity for item in provenance.input_refs}
    if any(item.occurrence_identity not in identities for item in required_inputs):
        return "provenance input evidence mismatch"
    if any(not _verify_ref(store, item) for item in provenance.input_refs):
        return "provenance input hash mismatch"
    return None


def audit_session(data_root: Path, session_id: str) -> list[str]:
    """Validate only F1's record/hash/session/correlation integrity boundary."""

    store = ForensicsEvidenceStore(data_root, session_id)
    issues: list[str] = []
    try:
        metadata = store.load_session()
        _require_validated_runtime_profile(metadata)
        external_hash = store.load_external_session_hash()
        producer_ref, config_ref = _producer_and_config_refs(metadata)
    except (ValueError, SessionIntegrityError) as error:
        return [str(error)]
    for label, ref in (("producer", producer_ref), ("verifier config", config_ref)):
        if not _verify_ref(store, ref):
            issues.append(f"{label} evidence hash mismatch")
    if producer_ref.source_id != "acr_forensics_producer_manifest":
        issues.append("producer evidence source mismatch")
    if config_ref.source_id != "acr_forensics_verifier_config":
        issues.append("verifier configuration source mismatch")
    try:
        verifier_spec = json.loads(store.blob_bytes(config_ref.blob_hash))
        if (
            metadata["verifier_spec_hash"] != config_ref.blob_hash
            or verifier_spec
            != {"command": metadata["verifier"], "match": "byte_exact", "version": "0.1"}
        ):
            issues.append("verifier configuration identity mismatch")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        issues.append("malformed verifier configuration evidence")

    checkpoints: dict[str, WorkspaceCheckpoint] = {}
    exact_pre_events: dict[str, tuple[AgentEvent, EvidenceRef]] = {}
    exact_post_events: dict[str, tuple[AgentEvent, EvidenceRef, dict[str, Any]]] = {}
    for path in store.record_files("events"):
        try:
            event = AgentEvent.model_validate_json(path.read_text())
            if event.session_id != session_id:
                raise ValueError("event session mismatch")
            if event.source_evidence_ref is None or not _verify_ref(store, event.source_evidence_ref):
                raise ValueError("event source evidence mismatch")
            if event.source_evidence_ref.source_id != "claude_hook_sanitized":
                raise ValueError("event source producer mismatch")
            if event.producer_ref != producer_ref:
                raise ValueError("event producer mismatch")
            provenance_issue = _provenance_issue(
                store,
                event.provenance_ref,
                producer_ref=producer_ref,
                output_object=event.id,
                required_inputs=[event.source_evidence_ref],
            )
            if provenance_issue:
                raise ValueError(provenance_issue)
            content = path.read_bytes()
            record_hash = sha256_bytes(content)
            if store.blob_bytes(record_hash) != content:
                raise ValueError("event occurrence blob mismatch")
            record_ref = EvidenceRef(
                blob_hash=record_hash,
                source_id="acr_forensics_record",
                trajectory_key=session_id,
                locator=f"/sessions/{session_id}/events/{event.id}.json",
                labels=[InformationLabel(scope="runtime", run_id=session_id)],
            )
            observation = json.loads(store.blob_bytes(event.source_evidence_ref.blob_hash))
            if observation.get("external_session_hash") != external_hash:
                raise ValueError("event external session mismatch")
            summary = observation.get("tool_input_summary")
            if (
                event.operation is not None
                and isinstance(summary, dict)
                and summary.get("command_class") == "exact_configured_verifier"
            ):
                if event.event_kind == "claude.PreToolUse":
                    if event.operation.occurrence_id in exact_pre_events:
                        raise ValueError("duplicate exact verifier pre-event occurrence")
                    exact_pre_events[event.operation.occurrence_id] = (event, record_ref)
                elif event.event_kind in {"claude.PostToolUse", "claude.PostToolUseFailure"}:
                    if event.operation.occurrence_id in exact_post_events:
                        raise ValueError("duplicate exact verifier result occurrence")
                    exact_post_events[event.operation.occurrence_id] = (
                        event,
                        record_ref,
                        observation,
                    )
        except (OSError, ValueError) as error:
            issues.append(f"invalid event {path.name}: {error}")
    for path in store.record_files("checkpoints"):
        try:
            checkpoint = WorkspaceCheckpoint.model_validate_json(path.read_text())
            if checkpoint.session_id != session_id:
                raise ValueError("checkpoint session mismatch")
            if checkpoint.producer_ref != producer_ref:
                raise ValueError("checkpoint producer mismatch")
            manifest = canonical_captured_state_manifest_bytes(
                checkpoint.git_base.value or "", checkpoint.captured_paths
            )
            if sha256_bytes(manifest) != checkpoint.captured_workspace_manifest_hash:
                raise ValueError("checkpoint canonical manifest mismatch")
            if store.blob_bytes(checkpoint.manifest_ref.blob_hash) != manifest:
                raise ValueError("checkpoint manifest bytes mismatch")
            manifest_path = store.data_root / "manifests" / (
                f"{checkpoint.captured_workspace_manifest_hash}.json"
            )
            if manifest_path.read_bytes() != manifest:
                raise ValueError("checkpoint manifest artifact mismatch")
            for captured in checkpoint.captured_paths:
                if not _verify_ref(store, captured.state_ref):
                    raise ValueError(f"captured state evidence mismatch: {captured.repo_relative_path}")
                if captured.content_ref is not None and not _verify_ref(store, captured.content_ref):
                    raise ValueError(f"captured blob mismatch: {captured.repo_relative_path}")
            checkpoint_content = path.read_bytes()
            if store.blob_bytes(sha256_bytes(checkpoint_content)) != checkpoint_content:
                raise ValueError("checkpoint occurrence blob mismatch")
            provenance_issue = _provenance_issue(
                store,
                checkpoint.provenance_ref,
                producer_ref=producer_ref,
                output_object=checkpoint.id,
                required_inputs=[checkpoint.manifest_ref],
            )
            if provenance_issue:
                raise ValueError(provenance_issue)
            checkpoints[checkpoint.id] = checkpoint
        except (OSError, ValueError) as error:
            issues.append(f"invalid checkpoint {path.name}: {error}")
    receipt_operations: set[str] = set()
    for path in store.record_files("receipts"):
        try:
            receipt = VerificationReceipt.model_validate_json(path.read_text())
            checkpoint = checkpoints[receipt.pre_checkpoint_id]
            if receipt.session_id != session_id or checkpoint.session_id != session_id:
                raise ValueError("receipt/checkpoint session mismatch")
            if (
                receipt.tested_captured_workspace_manifest_hash
                != checkpoint.captured_workspace_manifest_hash
            ):
                raise ValueError("receipt/checkpoint manifest mismatch")
            if receipt.verifier_config_ref != config_ref:
                raise ValueError("receipt verifier configuration mismatch")
            if receipt.verifier_spec_hash != config_ref.blob_hash:
                raise ValueError("receipt verifier specification hash mismatch")
            if receipt.producer_ref != producer_ref:
                raise ValueError("receipt producer mismatch")
            if receipt.operation is None:
                raise ValueError("receipt operation correlation missing")
            if receipt.operation.occurrence_id in receipt_operations:
                raise ValueError("duplicate trusted receipt occurrence")
            receipt_operations.add(receipt.operation.occurrence_id)
            pending = store.load_pending(receipt.operation.occurrence_id)
            pre_event, expected_pre_ref = exact_pre_events[receipt.operation.occurrence_id]
            post_event, expected_post_ref, post_observation = exact_post_events[
                receipt.operation.occurrence_id
            ]
            pending_pre_ref = EvidenceRef.model_validate(pending["pre_event_ref"])
            if pending_pre_ref != expected_pre_ref:
                raise ValueError("pending marker does not resolve its pre-event")
            terminal_result = _trusted_terminal_result(post_observation)
            if terminal_result is None:
                raise ValueError("receipt result event is not receipt-eligible")
            observed_passed, observed_exit_code = terminal_result
            if (
                receipt.passed.value != observed_passed
                or receipt.exit_code.value != observed_exit_code
            ):
                raise ValueError("receipt result does not match the correlated result event")
            if expected_post_ref.occurrence_identity not in {
                item.occurrence_identity for item in receipt.passed.refs
            }:
                raise ValueError("receipt result fact does not reference its result event")
            if expected_post_ref.occurrence_identity not in {
                item.occurrence_identity for item in receipt.exit_code.refs
            }:
                raise ValueError("receipt exit-code fact does not reference its result event")
            if expected_pre_ref.occurrence_identity not in {
                item.occurrence_identity for item in receipt.started_at.refs
            }:
                raise ValueError("receipt start fact does not reference its pre-event")
            if expected_post_ref.occurrence_identity not in {
                item.occurrence_identity for item in receipt.finished_at.refs
            }:
                raise ValueError("receipt finish fact does not reference its result event")
            if (
                pending.get("pre_sequence") != pre_event.ordering.sequence.value
                or receipt.ordering is None
                or receipt.ordering.sequence.value is None
                or post_event.ordering.sequence.value is None
                or receipt.ordering.sequence.value <= post_event.ordering.sequence.value
            ):
                raise ValueError("receipt ordering does not follow correlated events")
            if (
                pending.get("external_session_hash") != external_hash
                or pending.get("session_id") != session_id
                or pending.get("checkpoint_id") != checkpoint.id
                or pending.get("tested_manifest_hash")
                != checkpoint.captured_workspace_manifest_hash
                or pending.get("tool_use_id") != receipt.operation.occurrence_id
                or pending.get("verifier_spec_hash") != receipt.verifier_spec_hash
                or pending.get("command") != receipt.command.value
            ):
                raise ValueError("receipt correlation evidence mismatch")
            receipt_content = path.read_bytes()
            if store.blob_bytes(sha256_bytes(receipt_content)) != receipt_content:
                raise ValueError("receipt occurrence blob mismatch")
            checkpoint_ref = EvidenceRef.model_validate(pending["checkpoint_ref"])
            pre_event_ref = EvidenceRef.model_validate(pending["pre_event_ref"])
            provenance_issue = _provenance_issue(
                store,
                receipt.provenance_ref,
                producer_ref=producer_ref,
                output_object=receipt.id,
                required_inputs=[pre_event_ref, checkpoint_ref, expected_post_ref, config_ref],
            )
            if provenance_issue:
                raise ValueError(provenance_issue)
        except (OSError, KeyError, TypeError, ValueError) as error:
            issues.append(f"invalid receipt {path.name}: {error}")
    for operation_id in sorted(exact_pre_events):
        try:
            store.load_pending(operation_id)
        except (OSError, TypeError, ValueError):
            issues.append("exact verifier pre-state has no durable correlation")
    if exact_pre_events.keys() != exact_post_events.keys():
        issues.append("exact verifier pre/result occurrence correlation is incomplete")
    receipt_eligible_operations = {
        operation_id
        for operation_id, (_, _, observation) in exact_post_events.items()
        if _trusted_terminal_result(observation) is not None
    }
    if receipt_eligible_operations != receipt_operations:
        issues.append("receipt-eligible verifier result has no trusted receipt correlation")
    return issues


def _latest_receipt(store: ForensicsEvidenceStore) -> dict[str, Any] | None:
    receipts = [
        VerificationReceipt.model_validate_json(path.read_text())
        for path in store.record_files("receipts")
    ]
    if not receipts:
        return None
    latest = max(
        receipts,
        key=lambda item: item.ordering.sequence.value if item.ordering else -1,
    )
    return {
        "checkpoint": latest.tested_captured_workspace_manifest_hash,
        "result": "PASS" if latest.passed.value else "FAIL",
        "verifier": latest.command.value,
    }
