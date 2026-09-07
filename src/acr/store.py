"""Small immutable filesystem store for imported and runtime evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from acr.contracts import EvidenceRef, InformationLabel, Provenance


def _write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != content:
        raise ValueError(f"immutable artifact conflict: {path}")
    if not path.exists():
        path.write_bytes(content)


def ingest_bytes(
    raw: bytes,
    data_root: Path,
    source_id: str,
    trajectory_key: str,
    locator: str = "",
) -> EvidenceRef:
    digest = hashlib.sha256(raw).hexdigest()
    _write_once(data_root / "blobs" / digest, raw)
    return EvidenceRef(
        blob_hash=digest,
        source_id=source_id,
        trajectory_key=trajectory_key,
        locator=locator,
        labels=[InformationLabel(scope="analysis")],
    )


def ingest_runtime_bytes(raw: bytes, data_root: Path, run_id: str, locator: str) -> EvidenceRef:
    """Store one runtime occurrence without conflating it with byte identity."""

    return ingest_bytes(
        raw,
        data_root,
        source_id="acr_runtime",
        trajectory_key=run_id,
        locator=locator,
    ).model_copy(
        update={
            "labels": [
                InformationLabel(scope="runtime", run_id=run_id),
            ]
        }
    )


def load_blob(data_root: Path, blob_hash: str) -> bytes:
    return (data_root / "blobs" / blob_hash).read_bytes()


def persist_run_json(data_root: Path, run_id: str, name: str, value: Any) -> None:
    """Write a named runtime artifact exactly once under its run directory."""

    if "/" in name or name in {"", ".", ".."}:
        raise ValueError("invalid runtime artifact name")
    content = (
        value.model_dump_json(indent=2).encode() + b"\n"
        if hasattr(value, "model_dump_json")
        else json.dumps(value, sort_keys=True, indent=2).encode() + b"\n"
    )
    _write_once(data_root / "runs" / run_id / name, content)


def persist_run_jsonl(data_root: Path, run_id: str, name: str, values: list[Any]) -> None:
    """Persist a closed JSONL artifact exactly once; runtime never appends after seal."""

    if "/" in name or name in {"", ".", ".."}:
        raise ValueError("invalid runtime artifact name")
    content = b"".join(
        (item.model_dump_json() if hasattr(item, "model_dump_json") else json.dumps(item, sort_keys=True)).encode()
        + b"\n"
        for item in values
    )
    _write_once(data_root / "runs" / run_id / name, content)


def persist_physical_attempt(data_root: Path, run_id: str, value: Any) -> None:
    """Persist one physical attempt occurrence once; retries require a new ID."""

    identifier = value.id
    if "/" in identifier or identifier in {"", ".", ".."}:
        raise ValueError("invalid physical attempt identity")
    path = data_root / "runs" / run_id / "physical_attempts" / f"{identifier}.json"
    if path.exists():
        raise ValueError("physical attempt occurrence already exists")
    _write_once(path, value.model_dump_json(indent=2).encode() + b"\n")


def load_run_json(data_root: Path, run_id: str, name: str) -> Any:
    return json.loads((data_root / "runs" / run_id / name).read_text())


def persist_import(
    data_root: Path,
    import_id: str,
    manifest: dict[str, Any],
    raw_ref: EvidenceRef,
) -> None:
    root = data_root / "imports" / import_id
    _write_once(root / "source_manifest.json", json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n")
    _write_once(root / "raw_ref.json", raw_ref.model_dump_json(indent=2).encode() + b"\n")


def load_import(data_root: Path, import_id: str) -> tuple[dict[str, Any], EvidenceRef]:
    root = data_root / "imports" / import_id
    manifest = json.loads((root / "source_manifest.json").read_text())
    return manifest, EvidenceRef.model_validate_json((root / "raw_ref.json").read_text())


def persist_producer(data_root: Path, import_id: str, manifest: dict[str, Any]) -> EvidenceRef:
    content = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    ref = ingest_bytes(content, data_root, "acr_producer_manifest", import_id)
    root = data_root / "imports" / import_id
    _write_once(root / "producer_manifest.json", content)
    _write_once(root / "producer_ref.json", ref.model_dump_json(indent=2).encode() + b"\n")
    return ref


def load_producer(data_root: Path, import_id: str) -> EvidenceRef:
    return EvidenceRef.model_validate_json((data_root / "imports" / import_id / "producer_ref.json").read_text())


def load_producer_manifest(data_root: Path, import_id: str) -> bytes:
    return (data_root / "imports" / import_id / "producer_manifest.json").read_bytes()


def persist_normalized(data_root: Path, import_id: str, value: Any) -> None:
    _write_once(
        data_root / "imports" / import_id / "normalized.json",
        value.model_dump_json(indent=2).encode() + b"\n",
    )


def load_normalized(data_root: Path, import_id: str):
    from acr.adapters.legacy import NormalizedBatchRecord

    return NormalizedBatchRecord.model_validate_json(
        (data_root / "imports" / import_id / "normalized.json").read_text()
    )


def persist_provenance(data_root: Path, import_id: str, items: list[Provenance]) -> None:
    _write_once(
        data_root / "imports" / import_id / "provenance.jsonl",
        b"".join(item.model_dump_json().encode() + b"\n" for item in items),
    )


def load_provenance(data_root: Path, import_id: str) -> list[Provenance]:
    path = data_root / "imports" / import_id / "provenance.jsonl"
    return [Provenance.model_validate_json(line) for line in path.read_text().splitlines()]
