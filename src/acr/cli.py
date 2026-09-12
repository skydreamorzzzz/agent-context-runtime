"""ACR command-line entry points for the active and preserved research tracks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from acr.adapters.legacy import normalize
from acr.adapters.provider import CapturedProvider, DeepSeekHTTPTransport
from acr.audit import audit, audit_evaluation, audit_run
from acr.config import validate_run_config
from acr.contracts import Run
from acr.coverage import audit_coverage_report, render_coverage_markdown, scan_archive
from acr.demo_raw import DemoRawCaptureError, observe_demo_raw_hook
from acr.evaluation import LocalAddEvaluator
from acr.experiment import PairPreflightBlocked, prepare_noop_pair, run_noop_pair
from acr.forensics.session import (
    MAX_HOOK_INPUT_BYTES,
    SessionIntegrityError,
    audit_session,
    handle_claude_hook,
    run_claude_session,
)
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


def _within_attempt_budget(count: int, config: dict) -> bool:
    budget = config.get("budget")
    return (
        isinstance(budget, dict)
        and isinstance(budget.get("hard_max_physical_attempts"), int)
        and 1 <= count <= budget["hard_max_physical_attempts"]
    )


def main() -> None:
    parser = argparse.ArgumentParser(); commands = parser.add_subparsers(dest="command", required=True)
    claude = commands.add_parser("claude", help="run Claude Code with Agent Forensics capture")
    claude.add_argument("--config", default=".acr.json")
    claude.add_argument("--data-root")
    claude.add_argument(
        "--demo-raw-capture",
        action="store_true",
        help="opt in to sensitive local-only Claude trajectory capture",
    )
    claude.add_argument("claude_args", nargs=argparse.REMAINDER)
    hook = commands.add_parser("_forensics-hook", help="internal Claude hook endpoint")
    hook.add_argument("--data-root", required=True)
    hook.add_argument("--session-id", required=True)
    hook.add_argument("--repo-root", required=True)
    hook.add_argument("--demo-raw-session-dir")
    session_audit = commands.add_parser("audit-session")
    session_audit.add_argument("--data-root", required=True)
    session_audit.add_argument("--session-id", required=True)
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
    pair = commands.add_parser("pair-noop-deepseek")
    pair.add_argument("--data-root", required=True); pair.add_argument("--workspace-root", required=True)
    pair.add_argument("--private-spec", required=True); pair.add_argument("--pair-id", required=True)
    pair.add_argument("--replicate-id", default="aa-1")
    pair.add_argument("--execution-order", choices=("AB", "BA"), required=True)
    pair.add_argument("--config", default="configs/pilot.json")
    coverage = commands.add_parser("scan-duplicate-reads")
    coverage.add_argument("--archive", required=True)
    coverage.add_argument("--source-manifest", required=True)
    coverage.add_argument("--output", required=True)
    coverage.add_argument("--report", required=True)
    args = parser.parse_args(); root = Path(getattr(args, "data_root", ".") or ".")
    if args.command == "claude":
        forwarded = args.claude_args[1:] if args.claude_args[:1] == ["--"] else args.claude_args
        try:
            return_code, session_id, latest = run_claude_session(
                repo_root=Path.cwd(),
                config_path=Path(args.config),
                data_root_override=Path(args.data_root) if args.data_root else None,
                claude_args=forwarded,
                demo_raw_capture=args.demo_raw_capture,
            )
        except (ValueError, SessionIntegrityError) as error:
            raise SystemExit(f"BLOCKED: {error}") from None
        summary = {"latest_verifier": latest, "session_id": session_id}
        if args.demo_raw_capture:
            summary["demo_raw"] = str(
                Path.cwd().resolve() / ".acr" / "demo-raw" / session_id
            )
        print(json.dumps(summary, sort_keys=True))
        raise SystemExit(return_code)
    if args.command == "_forensics-hook":
        raw_input = sys.stdin.buffer.read(MAX_HOOK_INPUT_BYTES + 1)
        if args.demo_raw_session_dir:
            try:
                observe_demo_raw_hook(raw_input, Path(args.demo_raw_session_dir))
            except (DemoRawCaptureError, OSError, TypeError, ValueError) as error:
                print(f"Demo raw capture warning: {error}", file=sys.stderr)
        status = handle_claude_hook(
            raw_input=raw_input,
            data_root=Path(args.data_root),
            session_id=args.session_id,
            repo_root=Path(args.repo_root),
        )
        if status:
            print(
                "Agent Forensics blocked exact verifier: pre-state capture failed closed",
                file=sys.stderr,
            )
        raise SystemExit(status)
    if args.command == "audit-session":
        issues = audit_session(Path(args.data_root), args.session_id)
        print(json.dumps({"issues": issues, "status": "BLOCK" if issues else "PASS"}))
        raise SystemExit(bool(issues))
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
    if args.command == "pair-noop-deepseek":
        _run_noop_deepseek_pair(root, Path(args.workspace_root), Path(args.private_spec), args.pair_id, args.replicate_id, args.execution_order, Path(args.config))
        return
    if args.command == "scan-duplicate-reads":
        source = json.loads(Path(args.source_manifest).read_text())
        result = scan_archive(Path(args.archive), source)
        result_audit = audit_coverage_report(result, Path(args.archive), source)
        if result_audit.status != "PASS":
            print(json.dumps({"audit": result_audit.status, "blocks": result_audit.blocks}))
            raise SystemExit(1)
        output_path = Path(args.output)
        report_path = Path(args.report)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.model_dump_json(indent=2) + "\n")
        report_path.write_text(render_coverage_markdown(result, result_audit))
        print(
            json.dumps(
                {
                    "audit": result_audit.status,
                    "exact_content_duplicate_count": result.metrics[
                        "exact_content_duplicate_count"
                    ],
                    "strict_candidate_count": result.metrics["strict_candidate_count"],
                    "total_trajectories": result.metrics["total_trajectories"],
                    "verdict": result.verdict,
                },
                sort_keys=True,
            )
        )
        return
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
        _within_attempt_budget(outcome.physical_attempts, config)
        and outcome.file_reads >= 1
        and outcome.final_response_observed
        and outcome.run.status == "completed"
        and outcome.run.sealed_artifact_ref is not None
        and result.status == "PASS"
    )
    raise SystemExit(0 if accepted else 1)
def _run_noop_deepseek_pair(
    data_root: Path,
    workspace_root: Path,
    private_spec: Path,
    pair_id: str,
    replicate_id: str,
    execution_order: str,
    config_path: Path,
) -> None:
    """Execute one bounded real DeepSeek noop A/A pair, never an intervention."""

    if subprocess.check_output(["git", "status", "--porcelain"], text=True):
        raise SystemExit("BLOCKED: working tree is not clean")
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("BLOCKED: DEEPSEEK_API_KEY unavailable")
    if not private_spec.is_file():
        raise SystemExit("BLOCKED: private evaluator specification unavailable")
    config = json.loads(config_path.read_text())
    validate_run_config(config)
    required = {
        "provider": "deepseek", "model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com",
        "credential_source": "env:DEEPSEEK_API_KEY", "intervention": "noop", "cache_isolation": "unsupported",
    }
    if any(config.get(key) != value for key, value in required.items()):
        raise SystemExit("BLOCKED: config is not the frozen noop A/A configuration")
    manifest_path = Path(config["task_manifest"])
    try:
        task_manifest_bytes = manifest_path.read_bytes()
        task_manifest = json.loads(task_manifest_bytes)
        source_workspace = manifest_path.parent / task_manifest["workspace_source"]
        task = RuntimeTask(task_manifest["task_id"], task_manifest["public_instruction"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        raise SystemExit("BLOCKED: malformed public task manifest") from None
    if not source_workspace.is_dir():
        raise SystemExit("BLOCKED: public task workspace source is unavailable")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    try:
        plan = prepare_noop_pair(
            data_root=data_root, pair_id=pair_id, replicate_id=replicate_id, task_id=task.task_id,
            config=config, task_manifest_bytes=task_manifest_bytes, source_workspace=source_workspace,
            workspace_root=workspace_root, code_revision=revision,
            private_spec_sha256=hashlib.sha256(private_spec.read_bytes()).hexdigest(),
            execution_order=execution_order,
        )
    except (OSError, ValueError, PairPreflightBlocked) as error:
        raise SystemExit(f"BLOCKED: pair preflight failed: {error}") from None
    runtime_config = dict(config)
    runtime_config["code_revision"] = revision
    outcome = run_noop_pair(
        plan=plan, data_root=data_root, task=task,
        runtime_config_bytes=json.dumps(runtime_config, sort_keys=True, separators=(",", ":")).encode(),
        provider_factory=lambda: CapturedProvider(DeepSeekHTTPTransport(api_key=api_key, base_url=config["base_url"])),
        model=config["model"], source_workspace=source_workspace, private_spec=private_spec,
    )
    from acr.audit import audit_pair

    result = audit_pair(data_root, pair_id, str(private_spec))
    print(json.dumps({
        "audit": result.status, "pair_id": pair_id, "run_a": outcome.run_a.id,
        "run_b": outcome.run_b.id, "attempts_a": outcome.outcome_a.physical_attempts,
        "attempts_b": outcome.outcome_b.physical_attempts,
    }, sort_keys=True))
    accepted = (
        result.status == "PASS"
        and _within_attempt_budget(outcome.outcome_a.physical_attempts, config)
        and _within_attempt_budget(outcome.outcome_b.physical_attempts, config)
        and outcome.outcome_a.file_reads >= 1 and outcome.outcome_b.file_reads >= 1
        and outcome.outcome_a.final_response_observed and outcome.outcome_b.final_response_observed
        and outcome.run_a.status == "completed" and outcome.run_b.status == "completed"
    )
    raise SystemExit(0 if accepted else 1)


if __name__ == "__main__":
    main()
