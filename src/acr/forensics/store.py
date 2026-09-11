"""Immutable local evidence storage for one-session Agent Forensics capture."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from acr.contracts import EvidenceRef, InformationLabel, Provenance

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError(f"immutable evidence conflict: {path.name}") from None
        return
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class ForensicsEvidenceStore:
    """Filesystem store with immutable objects and a locked sequence allocator."""

    def __init__(self, data_root: Path, session_id: str):
        self.data_root = data_root.resolve()
        self.session_id = _safe_identifier(session_id, "session identity")
        self.session_root = self.data_root / "sessions" / self.session_id

    def ref_for_bytes(
        self,
        content: bytes,
        *,
        source_id: str,
        locator: str,
    ) -> EvidenceRef:
        digest = sha256_bytes(content)
        _write_once(self.data_root / "blobs" / digest, content)
        return EvidenceRef(
            blob_hash=digest,
            source_id=source_id,
            trajectory_key=self.session_id,
            locator=locator,
            labels=[InformationLabel(scope="runtime", run_id=self.session_id)],
        )

    def persist_manifest(self, content: bytes) -> EvidenceRef:
        digest = sha256_bytes(content)
        _write_once(self.data_root / "manifests" / f"{digest}.json", content)
        _write_once(self.data_root / "blobs" / digest, content)
        return EvidenceRef(
            blob_hash=digest,
            source_id="acr_forensics_manifest",
            trajectory_key=self.session_id,
            locator=f"/manifests/{digest}.json",
            labels=[InformationLabel(scope="runtime", run_id=self.session_id)],
        )

    def persist_record(self, category: str, value: Any) -> EvidenceRef:
        _safe_identifier(category, "record category")
        identifier = _safe_identifier(value.id, "record identity")
        content = value.model_dump_json(indent=2).encode() + b"\n"
        _write_once(self.session_root / category / f"{identifier}.json", content)
        return self.ref_for_bytes(
            content,
            source_id="acr_forensics_record",
            locator=f"/sessions/{self.session_id}/{category}/{identifier}.json",
        )

    def persist_provenance(
        self,
        *,
        identifier: str,
        producer_ref: EvidenceRef,
        output_object: str,
        input_refs: list[EvidenceRef],
        transform_name: str,
        config_ref: EvidenceRef | None = None,
    ) -> EvidenceRef:
        provenance = Provenance(
            kind="provenance",
            id=_safe_identifier(identifier, "provenance identity"),
            producer_ref=producer_ref,
            output_object=output_object,
            field="*",
            input_refs=input_refs,
            transform_name=transform_name,
            transform_version="0.1",
            config_ref=config_ref,
        )
        return self.persist_record("provenance", provenance)

    def initialize_session(
        self,
        *,
        repo_identity_hash: str,
        verifier: str,
        selected_untracked_paths: list[str],
        max_blob_bytes: int,
        claude_version: str,
    ) -> dict[str, Any]:
        producer_bytes = canonical_json_bytes(
            {
                "contract_status": "v0.1_frozen",
                "name": "acr.forensics",
                "producer_kind": "production_runtime",
                "version": "0.1.0",
            }
        )
        producer_ref = self.ref_for_bytes(
            producer_bytes,
            source_id="acr_forensics_producer_manifest",
            locator="/producer-manifest",
        )
        verifier_spec_bytes = canonical_json_bytes(
            {"command": verifier, "match": "byte_exact", "version": "0.1"}
        )
        config_ref = self.ref_for_bytes(
            verifier_spec_bytes,
            source_id="acr_forensics_verifier_config",
            locator="/verifier-config",
        )
        metadata = {
            "claude_version": claude_version,
            "config_ref": config_ref.model_dump(mode="json"),
            "external_session_hash": None,
            "max_blob_bytes": max_blob_bytes,
            "privacy": {
                "environment_values_persisted": False,
                "prompt_bodies_persisted": False,
                "raw_hook_payloads_persisted": False,
                "tool_response_bodies_persisted": False,
                "transcript_paths_persisted": False,
                "verifier_output_bodies_persisted": False,
            },
            "producer_ref": producer_ref.model_dump(mode="json"),
            "repo_identity_hash": repo_identity_hash,
            "schema": "acr.forensics-session/0.1",
            "selected_untracked_paths": selected_untracked_paths,
            "session_id": self.session_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "verifier": verifier,
            "verifier_spec_hash": config_ref.blob_hash,
        }
        _write_once(self.session_root / "session.json", canonical_json_bytes(metadata))
        return metadata

    def load_session(self) -> dict[str, Any]:
        try:
            value = json.loads((self.session_root / "session.json").read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("missing or malformed forensics session metadata") from error
        required = {
            "config_ref",
            "max_blob_bytes",
            "producer_ref",
            "repo_identity_hash",
            "selected_untracked_paths",
            "session_id",
            "verifier",
            "verifier_spec_hash",
        }
        if not isinstance(value, dict) or not required <= value.keys():
            raise ValueError("malformed forensics session metadata")
        if value["session_id"] != self.session_id:
            raise ValueError("forensics session metadata identity mismatch")
        if (
            not isinstance(value["verifier"], str)
            or not isinstance(value["verifier_spec_hash"], str)
            or not isinstance(value["repo_identity_hash"], str)
            or not isinstance(value["max_blob_bytes"], int)
            or not isinstance(value["selected_untracked_paths"], list)
        ):
            raise TypeError("malformed forensics session metadata values")
        return value

    def bind_external_session(self, external_session_hash: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", external_session_hash):
            raise ValueError("invalid external session hash")
        content = canonical_json_bytes(
            {
                "external_session_hash": external_session_hash,
                "schema": "acr.external-session-binding/0.1",
                "session_id": self.session_id,
            }
        )
        with self.locked():
            _write_once(self.session_root / "external_session.json", content)

    def load_external_session_hash(self) -> str:
        try:
            value = json.loads((self.session_root / "external_session.json").read_text())
            external_hash = value["external_session_hash"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise ValueError("missing or malformed external session binding") from error
        if not isinstance(external_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", external_hash):
            raise ValueError("malformed external session binding")
        return external_hash

    def persist_anomaly(self, reason: str, *, details: dict[str, Any] | None = None) -> None:
        value = {
            "details": details or {},
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "schema": "acr.capture-anomaly/0.1",
        }
        identifier = hashlib.sha256(
            canonical_json_bytes(value) + os.urandom(16)
        ).hexdigest()
        _write_once(
            self.session_root / "anomalies" / f"anomaly-{identifier}.json",
            canonical_json_bytes(value),
        )

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.session_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.session_root / ".lock"
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def reserve_sequence(self) -> int:
        with self.locked():
            path = self.session_root / ".sequence"
            try:
                current = int(path.read_text())
            except FileNotFoundError:
                current = 0
            except (OSError, UnicodeDecodeError, ValueError) as error:
                raise ValueError("malformed session sequence state") from error
            sequence = current + 1
            path.write_text(f"{sequence}\n")
            return sequence

    def pending_path(self, operation_id: str) -> Path:
        digest = sha256_bytes(operation_id.encode())
        return self.session_root / "pending_verifiers" / f"{digest}.json"

    def persist_pending(self, operation_id: str, value: dict[str, Any]) -> None:
        _write_once(self.pending_path(operation_id), canonical_json_bytes(value))

    def load_pending(self, operation_id: str) -> dict[str, Any]:
        try:
            value = json.loads(self.pending_path(operation_id).read_text())
        except FileNotFoundError:
            raise ValueError("no matching verifier pre-state correlation") from None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("malformed verifier pre-state correlation") from error
        if not isinstance(value, dict):
            raise TypeError("malformed verifier pre-state correlation")
        return value

    def record_path(self, category: str, identifier: str) -> Path:
        return self.session_root / _safe_identifier(category, "record category") / (
            f"{_safe_identifier(identifier, 'record identity')}.json"
        )

    def read_record(self, category: str, identifier: str) -> bytes:
        return self.record_path(category, identifier).read_bytes()

    def record_files(self, category: str) -> list[Path]:
        root = self.session_root / _safe_identifier(category, "record category")
        return sorted(root.glob("*.json")) if root.is_dir() else []

    def blob_bytes(self, digest: str) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid blob hash")
        return (self.data_root / "blobs" / digest).read_bytes()
