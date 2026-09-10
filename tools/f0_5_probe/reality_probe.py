#!/usr/bin/env python3
"""Disposable F0.5 Claude/Git reality probe; not a product API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

MANIFEST_FORMAT = "acr.captured-state-manifest/0.1-provisional"
PROBE_SCHEMA = "acr.f0.5-reality-probe/1"
DEFAULT_VERIFIER = "pytest -q"
EXCLUDED_PATHS = {".env"}
EXCLUDED_PREFIXES = (".acr-probe/", ".claude/", ".git/")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{serialized}\n".encode()


def write_once(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(value)
        path.chmod(0o444)
    except FileExistsError:
        if path.read_bytes() != value:
            raise RuntimeError(f"immutable evidence collision: {path.name}") from None


def run_git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
    )
    return result.stdout


def is_excluded(path: str) -> bool:
    return path in EXCLUDED_PATHS or path.startswith(EXCLUDED_PREFIXES)


def selected_paths_from_environment() -> list[str]:
    raw = os.environ.get("ACR_F05_SELECTED_UNTRACKED", "")
    return sorted({item for item in raw.split(":") if item and not is_excluded(item)})


def capture_state(
    repo: Path,
    evidence_dir: Path,
    selected_untracked: list[str],
) -> dict[str, Any]:
    started_wall_ns = time.time_ns()
    started_monotonic_ns = time.monotonic_ns()
    git_base = run_git(repo, "rev-parse", "HEAD").decode().strip()
    tracked = [
        item.decode()
        for item in run_git(repo, "ls-files", "-z").split(b"\0")
        if item
    ]

    path_kinds: dict[str, str] = {
        path: "tracked" for path in tracked if not is_excluded(path)
    }
    for path in selected_untracked:
        if path not in path_kinds:
            path_kinds[path] = "selected_untracked"

    entries: list[dict[str, str | None]] = []
    capture_gaps: list[dict[str, str]] = [
        {"path": ".env", "status": "excluded_by_policy"},
        {"area": "ignored_files", "status": "not_captured"},
        {"area": "environment", "status": "not_captured"},
        {"area": "running_processes", "status": "not_captured"},
    ]
    for relative_path in sorted(path_kinds):
        candidate = repo / relative_path
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_file()):
            capture_gaps.append(
                {"path": relative_path, "status": "unsupported_non_regular_file"}
            )
            continue
        if candidate.exists():
            content = candidate.read_bytes()
            content_hash = sha256_bytes(content)
            write_once(evidence_dir / "blobs" / content_hash, content)
            state = "present"
        else:
            content_hash = None
            state = "deleted"
        entries.append(
            {
                "content_hash": content_hash,
                "path": relative_path,
                "path_kind": path_kinds[relative_path],
                "state": state,
            }
        )

    manifest = {
        "format": MANIFEST_FORMAT,
        "git_base": git_base,
        "paths": entries,
    }
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_hash = sha256_bytes(manifest_bytes)
    write_once(evidence_dir / "manifests" / f"{manifest_hash}.json", manifest_bytes)
    finished_monotonic_ns = time.monotonic_ns()
    return {
        "capture_gaps": capture_gaps,
        "finished_monotonic_ns": finished_monotonic_ns,
        "git_base": git_base,
        "manifest_hash": manifest_hash,
        "manifest_ref": f"manifests/{manifest_hash}.json",
        "path_count": len(entries),
        "started_monotonic_ns": started_monotonic_ns,
        "started_wall_ns": started_wall_ns,
        "duration_ns": finished_monotonic_ns - started_monotonic_ns,
    }


def sanitize_path(value: object, project_root: Path) -> str:
    if not isinstance(value, str):
        return "unknown"
    try:
        path = Path(value).resolve()
        relative = path.relative_to(project_root)
    except (OSError, ValueError):
        return "outside_project_root"
    return "." if relative == Path(".") else relative.as_posix()


def sanitize_tool_input(
    tool_name: object,
    tool_input: object,
    project_root: Path,
    verifier: str,
) -> dict[str, Any]:
    if not isinstance(tool_input, dict):
        return {"shape": "non_object"}
    if tool_name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return {"command_class": "unknown"}
        if command == verifier:
            return {
                "command": verifier,
                "command_class": "exact_configured_verifier",
                "command_hash": sha256_bytes(command.encode()),
                "run_in_background": tool_input.get("run_in_background"),
            }
        return {
            "command_class": "other_not_persisted",
            "command_hash": sha256_bytes(command.encode()),
            "run_in_background": tool_input.get("run_in_background"),
        }
    if tool_name in {"Read", "Edit", "Write"}:
        return {
            "file_path": sanitize_path(tool_input.get("file_path"), project_root),
            "content_fields_excluded": sorted(
                key for key in ("content", "old_string", "new_string") if key in tool_input
            ),
        }
    return {"retained_field_names": sorted(str(key) for key in tool_input)}


def sanitized_hook_record(
    payload: dict[str, Any],
    project_root: Path,
    verifier: str,
) -> dict[str, Any]:
    event_name = payload.get("hook_event_name")
    retained_top_level = {
        "cwd",
        "duration_ms",
        "hook_event_name",
        "is_interrupt",
        "permission_mode",
        "prompt_id",
        "reason",
        "session_id",
        "source",
        "stop_hook_active",
        "tool_calls",
        "tool_input",
        "tool_name",
        "tool_use_id",
    }
    record: dict[str, Any] = {
        "cwd_scope": sanitize_path(payload.get("cwd"), project_root),
        "excluded_payload_fields": sorted(
            str(key) for key in payload if key not in retained_top_level
        ),
        "hook_event_name": event_name,
        "permission_mode": payload.get("permission_mode"),
        "pid": os.getpid(),
        "prompt_id": payload.get("prompt_id"),
        "received_monotonic_ns": time.monotonic_ns(),
        "received_wall_ns": time.time_ns(),
        "schema": PROBE_SCHEMA,
        "session_id": payload.get("session_id"),
    }
    if event_name in {"PreToolUse", "PostToolUse", "PostToolUseFailure"}:
        record.update(
            {
                "duration_ms": payload.get("duration_ms"),
                "is_interrupt": payload.get("is_interrupt"),
                "tool_input": sanitize_tool_input(
                    payload.get("tool_name"),
                    payload.get("tool_input"),
                    project_root,
                    verifier,
                ),
                "tool_name": payload.get("tool_name"),
                "tool_use_id": payload.get("tool_use_id"),
            }
        )
        if event_name == "PostToolUseFailure":
            error = payload.get("error")
            match = re.match(r"Exit code (\d+)", error) if isinstance(error, str) else None
            record["observed_exit_code"] = int(match.group(1)) if match else None
            record["error_body_persisted"] = False
    elif event_name == "PostToolBatch":
        record["tool_calls"] = [
            {
                "tool_input": sanitize_tool_input(
                    item.get("tool_name"),
                    item.get("tool_input"),
                    project_root,
                    verifier,
                ),
                "tool_name": item.get("tool_name"),
                "tool_use_id": item.get("tool_use_id"),
                "tool_response_persisted": False,
            }
            for item in payload.get("tool_calls", [])
            if isinstance(item, dict)
        ]
    elif event_name == "SessionStart":
        record["source"] = payload.get("source")
    elif event_name == "SessionEnd":
        record["reason"] = payload.get("reason")
    elif event_name == "Stop":
        background_tasks = payload.get("background_tasks")
        record["background_task_count"] = (
            len(background_tasks) if isinstance(background_tasks, list | dict) else None
        )
        record["stop_hook_active"] = payload.get("stop_hook_active")
        record["last_assistant_message_persisted"] = False
    elif event_name in {"SubagentStart", "SubagentStop"}:
        record["agent_id"] = payload.get("agent_id")
        record["agent_type"] = payload.get("agent_type")
    return record


def hook_command() -> int:
    evidence_dir = Path(os.environ["ACR_F05_EVIDENCE_DIR"]).resolve()
    raw_input = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw_input)
    except (json.JSONDecodeError, UnicodeDecodeError):
        anomaly = {
            "input_byte_count": len(raw_input),
            "input_status": "empty_or_malformed_not_persisted",
            "pid": os.getpid(),
            "received_monotonic_ns": time.monotonic_ns(),
            "received_wall_ns": time.time_ns(),
            "schema": PROBE_SCHEMA,
        }
        anomaly_bytes = json.dumps(anomaly, indent=2, sort_keys=True).encode() + b"\n"
        filename = f"{anomaly['received_wall_ns']}-{os.getpid()}-{uuid.uuid4().hex}.json"
        write_once(evidence_dir / "invocations" / filename, anomaly_bytes)
        return 0

    project_root = Path(os.environ["CLAUDE_PROJECT_DIR"]).resolve()
    verifier = os.environ.get("ACR_F05_VERIFIER", DEFAULT_VERIFIER)
    record = sanitized_hook_record(payload, project_root, verifier)
    tool_input = payload.get("tool_input")
    exact_verifier = (
        payload.get("tool_name") == "Bash"
        and isinstance(tool_input, dict)
        and tool_input.get("command") == verifier
    )
    if exact_verifier and payload.get("hook_event_name") == "PreToolUse":
        record["pre_state_capture"] = capture_state(
            project_root,
            evidence_dir,
            selected_paths_from_environment(),
        )
    elif exact_verifier and payload.get("hook_event_name") in {
        "PostToolUse",
        "PostToolUseFailure",
    }:
        record["verifier_tool_outcome"] = (
            "success_event"
            if payload.get("hook_event_name") == "PostToolUse"
            else "failure_event"
        )
        record["post_state_capture"] = capture_state(
            project_root,
            evidence_dir,
            selected_paths_from_environment(),
        )

    record["prepared_monotonic_ns"] = time.monotonic_ns()
    semantic_bytes = canonical_json_bytes(record)
    record["sanitized_payload_hash"] = sha256_bytes(semantic_bytes)
    evidence_bytes = json.dumps(record, indent=2, sort_keys=True).encode() + b"\n"
    filename = f"{record['received_wall_ns']}-{os.getpid()}-{uuid.uuid4().hex}.json"
    write_once(evidence_dir / "invocations" / filename, evidence_bytes)
    return 0


def restore_manifest(repo: Path, evidence_dir: Path, manifest_hash: str) -> None:
    manifest_path = evidence_dir / "manifests" / f"{manifest_hash}.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["paths"]:
        target = repo / entry["path"]
        if entry["state"] == "deleted":
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((evidence_dir / "blobs" / entry["content_hash"]).read_bytes())


def mutate_case(repo: Path, case: str, relative_path: str) -> None:
    target = repo / relative_path
    if case == "tracked_modification":
        target.write_bytes(target.read_bytes() + b"\n# f0.5 probe mutation\n")
    elif case in {"tracked_deletion", "selected_untracked_deletion"}:
        target.unlink()
    else:
        raise ValueError(f"unknown round-trip case: {case}")


def roundtrip_command(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence_dir = args.evidence_dir.resolve()
    selected = [args.selected_untracked]
    baseline = capture_state(repo, evidence_dir, selected)
    cases = [
        ("tracked_modification", args.modified_tracked),
        ("tracked_deletion", args.deleted_tracked),
        ("selected_untracked_deletion", args.selected_untracked),
    ]
    results: list[dict[str, Any]] = []
    for case, relative_path in cases:
        case_started_ns = time.monotonic_ns()
        mutate_case(repo, case, relative_path)
        mutated = capture_state(repo, evidence_dir, selected)
        restore_started_ns = time.monotonic_ns()
        restore_manifest(repo, evidence_dir, baseline["manifest_hash"])
        restore_finished_ns = time.monotonic_ns()
        restored = capture_state(repo, evidence_dir, selected)
        results.append(
            {
                "case": case,
                "manifest_changed_after_mutation": (
                    mutated["manifest_hash"] != baseline["manifest_hash"]
                ),
                "manifest_verified_after_restore": (
                    restored["manifest_hash"] == baseline["manifest_hash"]
                ),
                "path": relative_path,
                "restore_duration_ns": restore_finished_ns - restore_started_ns,
                "total_case_duration_ns": time.monotonic_ns() - case_started_ns,
            }
        )

    report = {
        "baseline_capture": baseline,
        "cases": results,
        "claim_scope": "captured_repository_scope",
        "excluded": [{"path": ".env", "status": "excluded_by_policy"}],
        "file_mode_semantics": "not_represented_by_f0_manifest",
        "result": "pass" if all(item["manifest_verified_after_restore"] for item in results) else "fail",
        "schema": PROBE_SCHEMA,
    }
    report_bytes = json.dumps(report, indent=2, sort_keys=True).encode() + b"\n"
    output = evidence_dir / "roundtrip" / f"{time.time_ns()}-{uuid.uuid4().hex}.json"
    write_once(output, report_bytes)
    print(json.dumps({"evidence": output.name, "result": report["result"]}, sort_keys=True))
    return 0 if report["result"] == "pass" else 1


def file_mode_command(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence_dir = args.evidence_dir.resolve()
    target = repo / args.path
    original_mode = target.stat().st_mode & 0o777
    baseline = capture_state(repo, evidence_dir, [])
    executable_mode = original_mode | 0o111
    target.chmod(executable_mode)
    changed = capture_state(repo, evidence_dir, [])
    restore_manifest(repo, evidence_dir, baseline["manifest_hash"])
    mode_after_content_restore = target.stat().st_mode & 0o777
    target.chmod(original_mode)
    report = {
        "baseline_manifest_hash": baseline["manifest_hash"],
        "claim": "file_mode_not_represented_or_restored",
        "executable_manifest_hash": changed["manifest_hash"],
        "manifest_distinguished_chmod": (
            baseline["manifest_hash"] != changed["manifest_hash"]
        ),
        "mode_after_content_restore": oct(mode_after_content_restore),
        "mode_before": oct(original_mode),
        "mode_changed_to": oct(executable_mode),
        "path": args.path,
        "restore_recovered_mode": mode_after_content_restore == original_mode,
        "schema": PROBE_SCHEMA,
    }
    report_bytes = json.dumps(report, indent=2, sort_keys=True).encode() + b"\n"
    output = evidence_dir / "file-mode" / f"{time.time_ns()}-{uuid.uuid4().hex}.json"
    write_once(output, report_bytes)
    print(json.dumps({"evidence": output.name, "result": report["claim"]}, sort_keys=True))
    return 0


def git_ref_command(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence_dir = args.evidence_dir.resolve()
    base_before_move = run_git(repo, "rev-parse", "HEAD").decode().strip()
    candidate_ref = f"refs/acr-probe/{uuid.uuid4().hex}"
    run_git(repo, "update-ref", candidate_ref, base_before_move)
    run_git(repo, "commit", "--allow-empty", "-m", "Advance disposable probe branch")
    head_after_move = run_git(repo, "rev-parse", "HEAD").decode().strip()
    pinned_after_move = run_git(repo, "rev-parse", candidate_ref).decode().strip()
    run_git(repo, "cat-file", "-e", f"{candidate_ref}^{{commit}}")
    report = {
        "base_before_branch_move": base_before_move,
        "candidate_ref": candidate_ref,
        "candidate_ref_naming_frozen": False,
        "candidate_ref_resolved_after_branch_move": pinned_after_move,
        "garbage_collection_retention_tested": False,
        "head_after_branch_move": head_after_move,
        "ref_preserved_base": pinned_after_move == base_before_move,
        "result": "candidate_ref_feasible_after_branch_move",
        "schema": PROBE_SCHEMA,
    }
    report_bytes = json.dumps(report, indent=2, sort_keys=True).encode() + b"\n"
    output = evidence_dir / "git-ref" / f"{time.time_ns()}-{uuid.uuid4().hex}.json"
    write_once(output, report_bytes)
    print(json.dumps({"evidence": output.name, "result": report["result"]}, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("hook")
    roundtrip = subcommands.add_parser("roundtrip")
    roundtrip.add_argument("--repo", type=Path, required=True)
    roundtrip.add_argument("--evidence-dir", type=Path, required=True)
    roundtrip.add_argument("--modified-tracked", required=True)
    roundtrip.add_argument("--deleted-tracked", required=True)
    roundtrip.add_argument("--selected-untracked", required=True)
    file_mode = subcommands.add_parser("file-mode")
    file_mode.add_argument("--repo", type=Path, required=True)
    file_mode.add_argument("--evidence-dir", type=Path, required=True)
    file_mode.add_argument("--path", required=True)
    git_ref = subcommands.add_parser("git-ref")
    git_ref.add_argument("--repo", type=Path, required=True)
    git_ref.add_argument("--evidence-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "hook":
        return hook_command()
    if args.command == "file-mode":
        return file_mode_command(args)
    if args.command == "git-ref":
        return git_ref_command(args)
    return roundtrip_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
