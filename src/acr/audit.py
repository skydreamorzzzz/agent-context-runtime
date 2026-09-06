"""Fail-closed audit of persisted M1 artifacts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from acr.provenance import resolve_json_pointer
from acr.store import load_blob, load_import, load_normalized, load_producer, load_provenance


@dataclass(frozen=True)
class AuditResult:
    status: str
    blocks: tuple[str, ...]


def audit(root: Path, import_id: str) -> AuditResult:
    blocks: list[str] = []
    _, raw_ref = load_import(root, import_id)
    normalized = load_normalized(root, import_id)
    producer_ref = load_producer(root, import_id)
    provenance = load_provenance(root, import_id)
    raw = load_blob(root, raw_ref.blob_hash)
    document = json.loads(raw)
    raw_steps = document["trajectory"]
    if hashlib.sha256(raw).hexdigest() != raw_ref.blob_hash:
        blocks.append("referenced_blob_hash_invalid")
    if len(normalized.steps) != len(raw_steps):
        blocks.append("normalized_structure_mismatch")
    expected = {(f"step:{i}", field) for i in range(len(raw_steps)) for field in ("action", "observation", "response")}
    groups: dict[tuple[str, str], list] = {}
    for item in provenance:
        groups.setdefault((item.output_object, item.field), []).append(item)
    if set(groups) != expected:
        blocks.append("required_provenance_missing")
    for key, items in groups.items():
        if len(items) != 1:
            blocks.append("conflicting_provenance")
            continue
        item = items[0]
        if item.producer_ref != producer_ref or normalized.producer_ref != producer_ref:
            blocks.append("producer_identity_mismatch")
        index = int(key[0].split(":")[1])
        if index >= len(normalized.steps) or normalized.steps[index].get("source_position") != index:
            blocks.append("source_position_mismatch")
            continue
        for ref in item.input_refs:
            try:
                referenced = load_blob(root, ref.blob_hash)
            except FileNotFoundError:
                blocks.append("referenced_blob_missing")
                continue
            if hashlib.sha256(referenced).hexdigest() != ref.blob_hash:
                blocks.append("referenced_blob_hash_invalid")
                continue
            if ref.source_id != raw_ref.source_id or ref.trajectory_key != raw_ref.trajectory_key:
                blocks.append("source_identity_mismatch")
                continue
            expected_locator = f"/trajectory/{index}/{key[1]}"
            if ref.locator != expected_locator:
                blocks.append("provenance_position_mismatch")
                continue
            try:
                value = resolve_json_pointer(json.loads(referenced), ref.locator)
            except (KeyError, IndexError, TypeError, ValueError):
                blocks.append("invalid_locator")
                continue
            if normalized.steps[index][key[1]] != value:
                blocks.append("normalized_value_mismatch")
    return AuditResult("BLOCK" if blocks else "PASS", tuple(sorted(set(blocks))))
