"""Immutable local raw-blob storage for M1 evidence validation."""
from __future__ import annotations

import hashlib
from pathlib import Path

from acr.contracts import EvidenceRef, InformationLabel


def ingest_bytes(raw: bytes, data_root: Path, source_id: str, trajectory_key: str, locator: str = "") -> EvidenceRef:
    digest = hashlib.sha256(raw).hexdigest()
    blob = data_root / "blobs" / digest
    blob.parent.mkdir(parents=True, exist_ok=True)
    if not blob.exists():
        blob.write_bytes(raw)
    if blob.read_bytes() != raw:
        raise ValueError("immutable blob integrity failure")
    return EvidenceRef(blob_hash=digest, source_id=source_id, trajectory_key=trajectory_key, locator=locator, labels=[InformationLabel(scope="analysis")])

def load_blob(data_root: Path, blob_hash: str) -> bytes:
    return (data_root / "blobs" / blob_hash).read_bytes()
