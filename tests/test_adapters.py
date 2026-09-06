"""Fixed-schema and persistence tests for the one real M1 fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from acr.adapters.legacy import ADAPTER_VERSION, NormalizedBatchRecord, normalize
from acr.contracts import Provenance
from acr.store import (
    ingest_bytes,
    load_blob,
    load_import,
    load_normalized,
    load_provenance,
    persist_import,
    persist_normalized,
    persist_producer,
    persist_provenance,
)

FIXTURE = Path("tests/fixtures/mswe_agent_demo/marshmallow-code__marshmallow-1867.traj")
MANIFEST = Path("tests/fixtures/mswe_agent_demo/source_manifest.json")


def producer_manifest() -> dict[str, str]:
    return {
        "producer_kind": "test_normalizer",
        "code_revision": "test-revision",
        "adapter_name": "legacy",
        "adapter_version": ADAPTER_VERSION,
        "schema_version": "1.0",
        "config_identity": "test-config-v1",
        "created_at": "2026-09-06T00:00:00+00:00",
    }


def build_import(root: Path, import_id: str = "one"):
    raw = FIXTURE.read_bytes()
    manifest = json.loads(MANIFEST.read_text())
    raw_ref = ingest_bytes(raw, root, "mswe_agent_demo", manifest["instance_id"])
    persist_import(root, import_id, manifest, raw_ref)
    producer_ref = persist_producer(root, import_id, producer_manifest())
    normalized, provenance = normalize(raw, raw_ref, producer_ref)
    persist_normalized(root, import_id, normalized)
    persist_provenance(root, import_id, provenance)
    return raw, manifest, raw_ref, producer_ref, normalized, provenance


def test_real_fixture_raw_integrity_ingest_idempotence_and_persisted_round_trip(tmp_path: Path) -> None:
    raw, manifest, raw_ref, producer_ref, normalized, provenance = build_import(tmp_path)

    assert len(raw) == 78826
    assert hashlib.sha256(raw).hexdigest() == manifest["raw_sha256"]
    assert load_blob(tmp_path, raw_ref.blob_hash) == raw
    assert ingest_bytes(raw, tmp_path, "mswe_agent_demo", manifest["instance_id"]) == raw_ref
    persisted_manifest, persisted_ref = load_import(tmp_path, "one")
    assert persisted_manifest == manifest
    assert persisted_ref == raw_ref
    assert load_normalized(tmp_path, "one") == normalized
    assert load_provenance(tmp_path, "one") == provenance
    assert Provenance.model_validate_json(provenance[0].model_dump_json()) == provenance[0]
    assert normalized.producer_ref == producer_ref
    assert all(item.producer_ref == producer_ref for item in provenance)


def test_fixed_schema_requires_observed_string_fields(tmp_path: Path) -> None:
    raw, _, raw_ref, producer_ref, _, _ = build_import(tmp_path)
    document = json.loads(raw)
    document["trajectory"][0]["action"] = 1
    with pytest.raises((TypeError, ValueError), match="trajectory step schema"):
        normalize(json.dumps(document).encode(), raw_ref, producer_ref)


def test_normalized_record_is_a_formal_envelope_and_writes_are_immutable(tmp_path: Path) -> None:
    _, _, _, _, normalized, _ = build_import(tmp_path)
    assert isinstance(normalized, NormalizedBatchRecord)
    assert normalized.kind == "normalized_batch"
    assert normalized.schema_version == "1.0"
    assert normalized.provenance_ref is None
    with pytest.raises(ValueError, match="immutable artifact conflict"):
        persist_normalized(tmp_path, "one", normalized.model_copy(update={"id": "different"}))
