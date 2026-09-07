"""Persisted-artifact M1 commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from acr.adapters.legacy import normalize
from acr.adapters.provider import CapturedProvider, DeepSeekHTTPTransport
from acr.audit import audit, audit_evaluation, audit_run
from acr.config import validate_run_config
from acr.contracts import Run
from acr.evaluation import LocalAddEvaluator
from acr.runtime.runner import CapturedRuntime, RuntimeTask, run_deepseek_add_smoke
from acr.store import (
    ingest_bytes,
    load_blob,
    load_import,
    load_producer,
    load_run_json,
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
    runtime_audit = commands.add_parser("audit-run")
    runtime_audit.add_argument("--data-root", required=True)
    runtime_audit.add_argument("--run-id", required=True)
    smoke = commands.add_parser("smoke-deepseek")
    smoke.add_argument("--data-root", required=True)
    smoke.add_argument("--workspace-root", required=True)
    smoke.add_argument("--config", default="configs/pilot.json")
    evaluate = commands.add_parser("evaluate-add")
    evaluate.add_argument("--data-root", required=True); evaluate.add_argument("--run-id", required=True)
    evaluate.add_argument("--sealed-workspace", required=True); evaluate.add_argument("--private-spec", required=True)
    args = parser.parse_args(); root = Path(args.data_root)
    if args.command == "ingest":
        manifest = json.loads(Path(args.manifest).read_text()); ref = ingest_bytes(Path(args.raw).read_bytes(), root, "mswe_agent_demo", manifest["instance_id"]); persist_import(root, args.import_id, manifest, ref); print(args.import_id); return
    if args.command == "audit-run":
        result = audit_run(root, args.run_id)
        print(result.status)
        raise SystemExit(result.status != "PASS")
    if args.command == "smoke-deepseek":
        _run_deepseek_smoke(root, Path(args.workspace_root), Path(args.config))
        return
    if args.command == "evaluate-add":
        run = Run.model_validate(load_run_json(root, args.run_id, "run.json"))
        result = LocalAddEvaluator(data_root=root, sealed_workspace=Path(args.sealed_workspace)).evaluate(run, args.private_spec)
        audit_result = audit_evaluation(root, args.run_id, args.private_spec)
        print(json.dumps({"audit": audit_result.status, "resolved": result.resolved.value, "status": result.status}, sort_keys=True))
        raise SystemExit(audit_result.status != "PASS")
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
    result = audit(root, args.import_id)
    print(result.status); raise SystemExit(result.status != "PASS")


def _run_deepseek_smoke(data_root: Path, workspace_root: Path, config_path: Path) -> None:
    """Run the explicitly requested, bounded real-provider smoke command."""

    if subprocess.check_output(["git", "status", "--porcelain"], text=True):
        raise SystemExit("BLOCKED: working tree is not clean")
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("BLOCKED: DEEPSEEK_API_KEY unavailable")
    config = json.loads(config_path.read_text())
    validate_run_config(config)
    expected = {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "credential_source": "env:DEEPSEEK_API_KEY",
        "intervention": "noop",
    }
    if any(config.get(key) != value for key, value in expected.items()):
        raise SystemExit("BLOCKED: pilot config is not the frozen DeepSeek smoke configuration")
    budget = config.get("budget")
    if not isinstance(budget, dict) or budget.get("hard_max_physical_attempts") != 5:
        raise SystemExit("BLOCKED: invalid physical attempt budget")
    manifest_path = Path(config["task_manifest"])
    manifest = json.loads(manifest_path.read_text())
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("task_id"), str)
        or not isinstance(manifest.get("public_instruction"), str)
        or not isinstance(manifest.get("workspace_source"), str)
    ):
        raise SystemExit("BLOCKED: malformed public task manifest")
    run_id = f"deepseek-smoke-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    workspace = workspace_root / run_id
    if workspace.exists():
        raise SystemExit("BLOCKED: fresh workspace path already exists")
    source_workspace = manifest_path.parent / manifest["workspace_source"]
    if not source_workspace.is_dir():
        raise SystemExit("BLOCKED: public task workspace source is unavailable")
    shutil.copytree(source_workspace, workspace)
    runtime_config = dict(config)
    runtime_config["code_revision"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    runtime = CapturedRuntime(
        data_root=data_root,
        run_id=run_id,
        task=RuntimeTask(manifest["task_id"], manifest["public_instruction"]),
        workspace=workspace,
        config_bytes=json.dumps(runtime_config, sort_keys=True, separators=(",", ":")).encode(),
        runtime_level="real_provider_smoke",
    )
    provider = CapturedProvider(
        DeepSeekHTTPTransport(api_key=api_key, base_url=config["base_url"])
    )
    outcome = run_deepseek_add_smoke(runtime, provider, model=config["model"])
    result = audit_run(data_root, run_id)
    summary = {
        "audit": result.status,
        "file_reads": outcome.file_reads,
        "physical_attempts": outcome.physical_attempts,
        "run_id": run_id,
        "run_status": outcome.run.status,
    }
    print(json.dumps(summary, sort_keys=True))
    accepted = (
        outcome.physical_attempts in {1, 2}
        and outcome.file_reads >= 1
        and outcome.final_response_observed
        and outcome.run.sealed_artifact_ref is not None
        and result.status == "PASS"
    )
    raise SystemExit(0 if accepted else 1)
