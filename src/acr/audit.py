"""Minimal fail-closed M1 evidence audit."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from acr.adapters.legacy import NormalizedLegacyTrajectory
from acr.provenance import resolve_json_pointer
from acr.store import load_blob


@dataclass(frozen=True)
class AuditResult:
    status: str
    blocks: tuple[str, ...]

def audit(data_root: Path, manifest: dict, normalized: NormalizedLegacyTrajectory) -> AuditResult:
    blocks=[]; raw_hash=manifest.get("raw_sha256")
    required=("upstream_repository","upstream_commit","artifact_path","instance_id","raw_sha256")
    if any(not manifest.get(k) for k in required): blocks.append("source_manifest_incomplete")
    try: raw=load_blob(data_root, raw_hash)
    except (FileNotFoundError, TypeError): return AuditResult("BLOCK", tuple(blocks+["raw_blob_missing"]))
    if hashlib.sha256(raw).hexdigest()!=raw_hash: blocks.append("hash_mismatch")
    try: document=json.loads(raw)
    except json.JSONDecodeError: blocks.append("raw_not_json"); document={}
    if len(normalized.provenance)<3: blocks.append("required_provenance_missing")
    for item in normalized.provenance:
        if not item.input_refs: blocks.append("observed_without_evidence"); continue
        try: resolve_json_pointer(document, item.input_refs[0].locator)
        except (KeyError, IndexError, ValueError, TypeError): blocks.append("invalid_locator")
    return AuditResult("BLOCK" if blocks else "PASS", tuple(sorted(set(blocks))))
