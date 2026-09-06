"""Regression tests for the persisted-evidence M1/M1.2 audit boundary."""

from __future__ import annotations

import json
from pathlib import Path

from test_adapters import build_import

from acr.audit import audit


def _normalized_path(root: Path) -> Path:
    return root / "imports" / "one" / "normalized.json"


def _provenance_path(root: Path) -> Path:
    return root / "imports" / "one" / "provenance.jsonl"


def _write_provenance(path: Path, items) -> None:
    path.write_text("".join(item.model_dump_json() + "\n" for item in items))


def test_good_persisted_chain_passes_and_source_binding_is_audited(tmp_path: Path) -> None:
    _, manifest, _, _, _, _ = build_import(tmp_path)
    assert audit(tmp_path, "one").status == "PASS"

    source_manifest = tmp_path / "imports" / "one" / "source_manifest.json"
    changed = dict(manifest)
    changed.pop("upstream_commit")
    source_manifest.write_text(json.dumps(changed))
    assert "source_manifest_incomplete" in audit(tmp_path, "one").blocks

    _, _, _, _, _, _ = build_import(tmp_path / "raw-ref")
    raw_ref_path = tmp_path / "raw-ref" / "imports" / "one" / "raw_ref.json"
    raw_ref = json.loads(raw_ref_path.read_text())
    raw_ref["trajectory_key"] = "other-instance"
    raw_ref_path.write_text(json.dumps(raw_ref))
    assert "source_identity_mismatch" in audit(tmp_path / "raw-ref", "one").blocks


def test_pinned_upstream_identity_tampering_blocks(tmp_path: Path) -> None:
    for field, replacement in (
        ("upstream_commit", "different-non-empty-revision"),
        ("upstream_repository", "https://github.com/example/other-repository"),
        ("artifact_path", "trajectories/other.traj"),
    ):
        root = tmp_path / field
        _, manifest, _, _, _, _ = build_import(root)
        changed = dict(manifest)
        changed[field] = replacement
        (root / "imports" / "one" / "source_manifest.json").write_text(json.dumps(changed))
        assert "pinned_source_identity_mismatch" in audit(root, "one").blocks


def test_retained_m1_mutations_block(tmp_path: Path) -> None:
    _, _, _, _, normalized, provenance = build_import(tmp_path)

    tampered = normalized.model_dump()
    tampered["steps"][0]["action"] = "malicious replacement"
    _normalized_path(tmp_path).write_text(json.dumps(tampered))
    assert "normalized_value_mismatch" in audit(tmp_path, "one").blocks

    _, _, _, _, _, provenance = build_import(tmp_path / "wrong-ref")
    changed = list(provenance)
    changed[0] = changed[0].model_copy(
        update={"input_refs": [changed[0].input_refs[0].model_copy(update={"blob_hash": "0" * 64})]}
    )
    _write_provenance(_provenance_path(tmp_path / "wrong-ref"), changed)
    assert "referenced_blob_missing" in audit(tmp_path / "wrong-ref", "one").blocks

    _, _, _, _, _, provenance = build_import(tmp_path / "bad-locator")
    changed = list(provenance)
    changed[0] = changed[0].model_copy(
        update={"input_refs": [changed[0].input_refs[0].model_copy(update={"locator": "/trajectory/0/nope"})]}
    )
    _write_provenance(_provenance_path(tmp_path / "bad-locator"), changed)
    blocks = audit(tmp_path / "bad-locator", "one").blocks
    assert "provenance_position_mismatch" in blocks
    assert "invalid_locator" in blocks

    _, _, _, _, _, provenance = build_import(tmp_path / "missing")
    _write_provenance(_provenance_path(tmp_path / "missing"), provenance[1:])
    assert "required_provenance_missing" in audit(tmp_path / "missing", "one").blocks

    _, _, _, _, _, provenance = build_import(tmp_path / "conflicting")
    _write_provenance(_provenance_path(tmp_path / "conflicting"), provenance + [provenance[0]])
    assert "conflicting_provenance" in audit(tmp_path / "conflicting", "one").blocks


def test_provenance_must_reference_this_imports_exact_raw_blob(tmp_path: Path) -> None:
    raw, _, _, _, _, provenance = build_import(tmp_path)
    alternate = json.loads(raw)
    alternate["trajectory"][1]["thought"] = "different but valid alternate raw artifact"
    from acr.store import ingest_bytes

    alternate_ref = ingest_bytes(
        json.dumps(alternate, sort_keys=True).encode(),
        tmp_path,
        "mswe_agent_demo",
        "marshmallow-code__marshmallow-1867",
    )
    changed = list(provenance)
    changed[0] = changed[0].model_copy(
        update={"input_refs": [changed[0].input_refs[0].model_copy(update={"blob_hash": alternate_ref.blob_hash})]}
    )
    _write_provenance(_provenance_path(tmp_path), changed)

    blocks = audit(tmp_path, "one").blocks
    assert "provenance_raw_blob_mismatch" in blocks
    assert "referenced_blob_missing" not in blocks


def test_raw_corruption_producer_reference_and_malformed_artifacts_block(tmp_path: Path) -> None:
    _, _, raw_ref, _, _, _ = build_import(tmp_path)
    (tmp_path / "blobs" / raw_ref.blob_hash).write_bytes(b"corrupt")
    assert "referenced_blob_hash_invalid" in audit(tmp_path, "one").blocks

    build_import(tmp_path / "producer")
    producer_ref_path = tmp_path / "producer" / "imports" / "one" / "producer_ref.json"
    changed_ref = json.loads(producer_ref_path.read_text())
    changed_ref["blob_hash"] = "0" * 64
    producer_ref_path.write_text(json.dumps(changed_ref))
    assert "referenced_blob_missing" in audit(tmp_path / "producer", "one").blocks

    build_import(tmp_path / "producer-file")
    (tmp_path / "producer-file" / "imports" / "one" / "producer_manifest.json").write_text("{}")
    assert "producer_manifest_mismatch" in audit(tmp_path / "producer-file", "one").blocks

    _, _, _, _, _, _ = build_import(tmp_path / "malformed")
    _normalized_path(tmp_path / "malformed").write_text("not-json")
    assert "malformed_persisted_evidence" in audit(tmp_path / "malformed", "one").blocks

    _, _, _, _, normalized, _ = build_import(tmp_path / "environment")
    changed = normalized.model_dump()
    changed["environment"] = "tampered"
    _normalized_path(tmp_path / "environment").write_text(json.dumps(changed))
    assert "normalized_environment_mismatch" in audit(tmp_path / "environment", "one").blocks


def test_m12_raw_driven_structure_and_position_attacks_block(tmp_path: Path) -> None:
    _, _, _, _, normalized, provenance = build_import(tmp_path)
    deleted = normalized.model_dump()
    deleted["steps"].pop()
    _normalized_path(tmp_path).write_text(json.dumps(deleted))
    _write_provenance(_provenance_path(tmp_path), provenance[:-3])
    assert "normalized_structure_mismatch" in audit(tmp_path, "one").blocks

    _, _, _, _, normalized, _ = build_import(tmp_path / "empty")
    empty = normalized.model_dump()
    empty["steps"] = []
    _normalized_path(tmp_path / "empty").write_text(json.dumps(empty))
    _provenance_path(tmp_path / "empty").write_text("")
    blocks = audit(tmp_path / "empty", "one").blocks
    assert "normalized_structure_mismatch" in blocks
    assert "required_provenance_missing" in blocks

    _, _, _, _, normalized, provenance = build_import(tmp_path / "position")
    changed = normalized.model_dump()
    changed["steps"][0].update(
        {field: changed["steps"][5][field] for field in ("action", "observation", "response")}
    )
    _normalized_path(tmp_path / "position").write_text(json.dumps(changed))
    laundered = []
    for item in provenance:
        if item.output_object == "step:0":
            item = item.model_copy(
                update={
                    "input_refs": [
                        item.input_refs[0].model_copy(
                            update={"locator": item.input_refs[0].locator.replace("/0/", "/5/")}
                        )
                    ]
                }
            )
        laundered.append(item)
    _write_provenance(_provenance_path(tmp_path / "position"), laundered)
    assert "provenance_position_mismatch" in audit(tmp_path / "position", "one").blocks

    _, _, _, _, normalized, _ = build_import(tmp_path / "source-position")
    changed = normalized.model_dump()
    changed["steps"][0]["source_position"] = 5
    _normalized_path(tmp_path / "source-position").write_text(json.dumps(changed))
    assert "source_position_mismatch" in audit(tmp_path / "source-position", "one").blocks
