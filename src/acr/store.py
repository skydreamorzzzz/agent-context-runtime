"""Small immutable filesystem store for the single M1 import."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from acr.contracts import EvidenceRef, InformationLabel, Provenance


def _write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != content: raise ValueError(f"immutable artifact conflict: {path}")
    if not path.exists(): path.write_bytes(content)

def ingest_bytes(raw: bytes, data_root: Path, source_id: str, trajectory_key: str, locator: str = "") -> EvidenceRef:
    digest=hashlib.sha256(raw).hexdigest(); _write_once(data_root/"blobs"/digest, raw)
    return EvidenceRef(blob_hash=digest,source_id=source_id,trajectory_key=trajectory_key,locator=locator,labels=[InformationLabel(scope="analysis")])
def load_blob(data_root: Path, blob_hash: str) -> bytes: return (data_root/"blobs"/blob_hash).read_bytes()
def persist_import(data_root: Path, import_id: str, manifest: dict[str, Any], raw_ref: EvidenceRef) -> None:
    root=data_root/"imports"/import_id
    _write_once(root/"source_manifest.json", json.dumps(manifest,sort_keys=True,indent=2).encode()+b"\n")
    _write_once(root/"raw_ref.json", raw_ref.model_dump_json(indent=2).encode()+b"\n")
def load_import(data_root: Path, import_id: str) -> tuple[dict[str,Any],EvidenceRef]:
    root=data_root/"imports"/import_id
    return json.loads((root/"source_manifest.json").read_text()), EvidenceRef.model_validate_json((root/"raw_ref.json").read_text())
def persist_normalized(data_root: Path, import_id: str, value: dict[str,Any]) -> None: _write_once(data_root/"imports"/import_id/"normalized.json",json.dumps(value,sort_keys=True).encode()+b"\n")
def load_normalized(data_root: Path, import_id: str) -> dict[str,Any]: return json.loads((data_root/"imports"/import_id/"normalized.json").read_text())
def persist_provenance(data_root: Path, import_id: str, items: list[Provenance]) -> None: _write_once(data_root/"imports"/import_id/"provenance.jsonl",b"".join(x.model_dump_json().encode()+b"\n" for x in items))
def load_provenance(data_root: Path, import_id: str) -> list[Provenance]: return [Provenance.model_validate_json(x) for x in (data_root/"imports"/import_id/"provenance.jsonl").read_text().splitlines()]
