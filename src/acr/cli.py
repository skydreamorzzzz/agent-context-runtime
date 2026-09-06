"""M1 persisted-artifact commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from acr.adapters.legacy import normalize
from acr.audit import audit
from acr.store import (
    ingest_bytes,
    load_blob,
    load_import,
    persist_import,
    persist_normalized,
    persist_provenance,
)


def main()->None:
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest="cmd",required=True)
    a=s.add_parser("ingest"); a.add_argument("--raw",required=True); a.add_argument("--manifest",required=True); a.add_argument("--data-root",required=True); a.add_argument("--import-id",required=True)
    for name in ("normalize","audit"):
        a=s.add_parser(name); a.add_argument("--data-root",required=True); a.add_argument("--import-id",required=True)
    x=p.parse_args(); root=Path(x.data_root)
    if x.cmd=="ingest":
        raw=Path(x.raw).read_bytes(); manifest=json.loads(Path(x.manifest).read_text()); ref=ingest_bytes(raw,root,"mswe_agent_demo",manifest["instance_id"]); persist_import(root,x.import_id,manifest,ref); print(json.dumps({"import_id":x.import_id,"raw_ref":ref.model_dump()})); return
    manifest,ref=load_import(root,x.import_id)
    if x.cmd=="normalize":
        normalized,provenance=normalize(load_blob(root,ref.blob_hash),ref); persist_normalized(root,x.import_id,normalized); persist_provenance(root,x.import_id,provenance); print(json.dumps({"steps":len(normalized["steps"]),"provenance":len(provenance)})); return
    result=audit(root,x.import_id); print(json.dumps({"status":result.status,"blocks":result.blocks})); raise SystemExit(result.status!="PASS")
