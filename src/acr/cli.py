"""M1 commands for one raw trajectory evidence chain."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from acr.adapters.legacy import normalize
from acr.audit import audit
from acr.store import ingest_bytes


def main() -> None:
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="command", required=True)
    for name in ("ingest","normalize","audit"):
        p=sub.add_parser(name); p.add_argument("--raw", required=True); p.add_argument("--manifest", required=True); p.add_argument("--data-root", required=True)
    args=parser.parse_args(); raw=Path(args.raw).read_bytes(); manifest=json.loads(Path(args.manifest).read_text()); root=Path(args.data_root)
    ref=ingest_bytes(raw, root, "mswe_agent_demo", manifest["instance_id"])
    if args.command=="ingest": print(ref.model_dump_json()); return
    result=normalize(raw, ref)
    if args.command=="normalize": print(json.dumps({"steps":len(result.steps),"provenance":len(result.provenance),"adapter_version":"mswe_agent_demo_traj_v1"})); return
    outcome=audit(root, manifest, result); print(json.dumps({"status":outcome.status,"blocks":outcome.blocks})); raise SystemExit(0 if outcome.status=="PASS" else 1)
