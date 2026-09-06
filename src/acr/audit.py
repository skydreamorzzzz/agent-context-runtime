"""Fail-closed audit of persisted M1 artifacts only."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from acr.adapters.legacy import ADAPTER_VERSION, parse_document
from acr.contracts import EvidenceRef, Provenance
from acr.provenance import resolve_json_pointer
from acr.store import (
    load_blob,
    load_import,
    load_normalized,
    load_producer,
    load_producer_manifest,
    load_provenance,
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
