"""Fail-closed audit of persisted M1 artifacts only."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from acr.provenance import resolve_json_pointer
from acr.store import load_blob, load_import, load_normalized, load_provenance


@dataclass(frozen=True)
class AuditResult: status:str; blocks:tuple[str,...]
def audit(data_root:Path, import_id:str)->AuditResult:
    blocks=[]; manifest,raw_ref=load_import(data_root,import_id); normalized=load_normalized(data_root,import_id); provenance=load_provenance(data_root,import_id)
    if any(not manifest.get(k) for k in ("upstream_repository","upstream_commit","artifact_path","instance_id","raw_sha256")): blocks.append("source_manifest_incomplete")
    if raw_ref.blob_hash!=manifest.get("raw_sha256") or raw_ref.source_id!="mswe_agent_demo" or raw_ref.trajectory_key!=manifest.get("instance_id"): blocks.append("source_identity_mismatch")
    expected={(f"step:{i}",f) for i in range(len(normalized.get("steps",[]))) for f in ("action","observation","response")}; grouped={}
    for p in provenance: grouped.setdefault((p.output_object,p.field),[]).append(p)
    if set(grouped)!=expected: blocks.append("required_provenance_missing")
    if any(len(v)!=1 for v in grouped.values()): blocks.append("conflicting_provenance")
    for items in grouped.values():
        if len(items)!=1: continue
        p=items[0]
        for ref in p.input_refs:
            try: raw=load_blob(data_root,ref.blob_hash)
            except FileNotFoundError: blocks.append("referenced_blob_missing"); continue
            if hashlib.sha256(raw).hexdigest()!=ref.blob_hash: blocks.append("referenced_blob_hash_invalid"); continue
            if ref.source_id!=raw_ref.source_id or ref.trajectory_key!=raw_ref.trajectory_key: blocks.append("source_identity_mismatch"); continue
            try: value=resolve_json_pointer(json.loads(raw),ref.locator)
            except (KeyError,IndexError,TypeError,ValueError,json.JSONDecodeError): blocks.append("invalid_locator"); continue
            index=int(p.output_object.split(":")[1]);
            if normalized["steps"][index][p.field]!=value: blocks.append("normalized_value_mismatch")
    return AuditResult("BLOCK" if blocks else "PASS",tuple(sorted(set(blocks))))
