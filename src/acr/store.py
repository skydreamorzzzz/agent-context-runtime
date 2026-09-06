"""Immutable filesystem store for the single M1 import."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from acr.contracts import EvidenceRef, InformationLabel, Provenance


def _write_once(path:Path,content:bytes)->None:
 path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists() and path.read_bytes()!=content: raise ValueError(f"immutable artifact conflict: {path}")
 if not path.exists(): path.write_bytes(content)
def ingest_bytes(raw:bytes,data_root:Path,source_id:str,trajectory_key:str,locator:str="")->EvidenceRef:
 h=hashlib.sha256(raw).hexdigest(); _write_once(data_root/"blobs"/h,raw); return EvidenceRef(blob_hash=h,source_id=source_id,trajectory_key=trajectory_key,locator=locator,labels=[InformationLabel(scope="analysis")])
def load_blob(root:Path,h:str)->bytes:return (root/"blobs"/h).read_bytes()
def persist_import(root:Path,i:str,m:dict[str,Any],ref:EvidenceRef)->None:
 _write_once(root/"imports"/i/"source_manifest.json",json.dumps(m,sort_keys=True,indent=2).encode()+b"\n"); _write_once(root/"imports"/i/"raw_ref.json",ref.model_dump_json(indent=2).encode()+b"\n")
def load_import(root:Path,i:str):
 p=root/"imports"/i; return json.loads((p/"source_manifest.json").read_text()),EvidenceRef.model_validate_json((p/"raw_ref.json").read_text())
def persist_producer(root:Path,i:str,m:dict[str,Any])->EvidenceRef:
 b=json.dumps(m,sort_keys=True,indent=2).encode()+b"\n"; ref=ingest_bytes(b,root,"acr_producer_manifest",i); _write_once(root/"imports"/i/"producer_manifest.json",b); _write_once(root/"imports"/i/"producer_ref.json",ref.model_dump_json().encode()+b"\n"); return ref
def load_producer(root:Path,i:str)->EvidenceRef:return EvidenceRef.model_validate_json((root/"imports"/i/"producer_ref.json").read_text())
def persist_normalized(root:Path,i:str,x:Any)->None:_write_once(root/"imports"/i/"normalized.json",x.model_dump_json(indent=2).encode()+b"\n")
def load_normalized(root:Path,i:str):
 from acr.adapters.legacy import NormalizedBatchRecord
 return NormalizedBatchRecord.model_validate_json((root/"imports"/i/"normalized.json").read_text())
def persist_provenance(root:Path,i:str,x:list[Provenance])->None:_write_once(root/"imports"/i/"provenance.jsonl",b"".join(v.model_dump_json().encode()+b"\n" for v in x))
def load_provenance(root:Path,i:str)->list[Provenance]:return [Provenance.model_validate_json(v) for v in (root/"imports"/i/"provenance.jsonl").read_text().splitlines()]
