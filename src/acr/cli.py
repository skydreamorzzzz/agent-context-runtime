"""Persisted-artifact M1 commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from acr.adapters.legacy import normalize
from acr.audit import audit
from acr.store import (
    ingest_bytes,
    load_blob,
    load_import,
    load_producer,
    persist_import,
    persist_normalized,
    persist_producer,
    persist_provenance,
)


def main() -> None:
    parser = argparse.ArgumentParser(); commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("--raw", required=True); ingest.add_argument("--manifest", required=True); ingest.add_argument("--data-root", required=True); ingest.add_argument("--import-id", required=True)
    for name in ("normalize", "audit"):
        command = commands.add_parser(name); command.add_argument("--data-root", required=True); command.add_argument("--import-id", required=True)
    args = parser.parse_args(); root = Path(args.data_root)
    if args.command == "ingest":
        manifest = json.loads(Path(args.manifest).read_text()); ref = ingest_bytes(Path(args.raw).read_bytes(), root, "mswe_agent_demo", manifest["instance_id"]); persist_import(root, args.import_id, manifest, ref); print(args.import_id); return
    _, raw_ref = load_import(root, args.import_id)
    if args.command == "normalize":
        producer_path = root / "imports" / args.import_id / "producer_ref.json"
        if producer_path.exists():
            producer = load_producer(root, args.import_id)
        else:
            code_revision = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip()
            config_identity = hashlib.sha256(
                b"legacy|mswe_agent_demo_traj_v1|schema=1.0"
            ).hexdigest()
            producer = persist_producer(
                root,
                args.import_id,
                {
                    "producer_kind": "acr_normalizer",
                    "code_revision": code_revision,
                    "adapter_name": "legacy",
                    "adapter_version": "mswe_agent_demo_traj_v1",
                    "schema_version": "1.0",
                    "config_identity": config_identity,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        normalized, provenance = normalize(load_blob(root, raw_ref.blob_hash), raw_ref, producer); persist_normalized(root, args.import_id, normalized); persist_provenance(root, args.import_id, provenance); print(len(normalized.steps)); return
    result = audit(root, args.import_id); print(result.status); raise SystemExit(result.status != "PASS")
