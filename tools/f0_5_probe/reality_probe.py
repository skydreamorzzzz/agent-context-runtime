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

MANIFEST_FORMAT = "acr.captured-state-manifest/0.2-provisional"
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
            executable = bool(candidate.stat().st_mode & 0o111)
            state = "present"
        else:
            content_hash = None
            executable = None
            state = "deleted"
        entries.append(
            {
                "content_hash": content_hash,
                "executable": executable,
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
        current_mode = target.stat().st_mode
        restored_mode = (
            current_mode | 0o111
            if entry["executable"]
            else current_mode & ~0o111
        )
        target.chmod(restored_mode)


def executable_state(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)


def set_executable_state(path: Path, executable: bool) -> None:
    current_mode = path.stat().st_mode
    path.chmod(current_mode | 0o111 if executable else current_mode & ~0o111)


def evidence_reference(evidence_dir: Path, relative_path: str) -> dict[str, str]:
    artifact = (evidence_dir / relative_path).resolve()
    artifact.relative_to(evidence_dir.resolve())
    return {
        "path": artifact.relative_to(evidence_dir.resolve()).as_posix(),
        "sha256": sha256_bytes(artifact.read_bytes()),
    }


def load_evidence_json(evidence_dir: Path, relative_path: str) -> dict[str, Any]:
    artifact = (evidence_dir / relative_path).resolve()
    artifact.relative_to(evidence_dir.resolve())
    value = json.loads(artifact.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object evidence: {relative_path}")
    return value


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


def executable_mode_command(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence_dir = args.evidence_dir.resolve()
    selected = [args.selected_untracked]
    baseline = capture_state(repo, evidence_dir, selected)
    case_specs = [
        ("tracked_false_to_true", args.non_executable_tracked, False),
        ("tracked_true_to_false", args.executable_tracked, True),
        ("selected_untracked_true_to_false", args.selected_untracked, True),
    ]
    cases: list[dict[str, Any]] = []
    for case, relative_path, expected_baseline in case_specs:
        target = repo / relative_path
        baseline_executable = executable_state(target)
        if baseline_executable is not expected_baseline:
            raise ValueError(f"unexpected baseline executable state for {relative_path}")
        set_executable_state(target, not baseline_executable)
        mutated = capture_state(repo, evidence_dir, selected)
        restore_manifest(repo, evidence_dir, baseline["manifest_hash"])
        restored = capture_state(repo, evidence_dir, selected)
        cases.append(
            {
                "baseline_executable": baseline_executable,
                "case": case,
                "manifest_changed_after_executable_mutation": (
                    mutated["manifest_hash"] != baseline["manifest_hash"]
                ),
                "manifest_verified_after_restore": (
                    restored["manifest_hash"] == baseline["manifest_hash"]
                ),
                "path": relative_path,
                "restored_executable": executable_state(target),
            }
        )

    passed = all(
        item["manifest_changed_after_executable_mutation"]
        and item["manifest_verified_after_restore"]
        and item["restored_executable"] == item["baseline_executable"]
        for item in cases
    )
    report = {
        "baseline_manifest_hash": baseline["manifest_hash"],
        "cases": cases,
        "claim_scope": "captured_present_regular_file_executable_boolean",
        "excluded": [{"path": ".env", "status": "excluded_by_policy"}],
        "result": "pass" if passed else "fail",
        "schema": PROBE_SCHEMA,
    }
    report_bytes = json.dumps(report, indent=2, sort_keys=True).encode() + b"\n"
    output = evidence_dir / "executable-mode" / f"{time.time_ns()}-{uuid.uuid4().hex}.json"
    write_once(output, report_bytes)
    print(json.dumps({"evidence": output.name, "result": report["result"]}, sort_keys=True))
    return 0 if passed else 1


def integrated_restore_command(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence_dir = args.evidence_dir.resolve()
    selected = [args.selected_untracked]
    pass_pre = load_evidence_json(evidence_dir, args.pass_pre_event)
    pass_post = load_evidence_json(evidence_dir, args.pass_post_event)
    fail_pre = load_evidence_json(evidence_dir, args.fail_pre_event)
    fail_post = load_evidence_json(evidence_dir, args.fail_post_event)
    mutation = load_evidence_json(evidence_dir, args.mutation_event)
    pass_result = load_evidence_json(evidence_dir, args.pass_result_marker)
    fail_result = load_evidence_json(evidence_dir, args.fail_result_marker)

    pass_hash = pass_pre["pre_state_capture"]["manifest_hash"]
    fail_hash = fail_pre["pre_state_capture"]["manifest_hash"]
    pass_manifest = load_evidence_json(evidence_dir, f"manifests/{pass_hash}.json")
    fail_manifest = load_evidence_json(evidence_dir, f"manifests/{fail_hash}.json")
    session_ids = {
        pass_pre.get("session_id"),
        pass_post.get("session_id"),
        fail_pre.get("session_id"),
        fail_post.get("session_id"),
        mutation.get("session_id"),
    }
    same_session = len(session_ids) == 1 and None not in session_ids
    verifier_events_match = (
        pass_pre.get("tool_use_id") == pass_post.get("tool_use_id")
        and fail_pre.get("tool_use_id") == fail_post.get("tool_use_id")
        and pass_pre.get("tool_input", {}).get("command_class")
        == "exact_configured_verifier"
        and fail_pre.get("tool_input", {}).get("command_class")
        == "exact_configured_verifier"
    )
    results_match = (
        pass_post.get("hook_event_name") == "PostToolUse"
        and pass_result.get("exit_status") == 0
        and fail_post.get("hook_event_name") == "PostToolUseFailure"
        and fail_result.get("exit_status") not in {None, 0}
    )
    mutation_observed = (
        mutation.get("hook_event_name") == "PostToolUse"
        and mutation.get("tool_name") in {"Edit", "Write"}
        and pass_post["received_wall_ns"]
        < mutation["received_wall_ns"]
        < fail_pre["received_wall_ns"]
    )
    same_git_base = pass_manifest["git_base"] == fail_manifest["git_base"]
    same_captured_paths = [
        (item["path"], item["path_kind"]) for item in pass_manifest["paths"]
    ] == [(item["path"], item["path_kind"]) for item in fail_manifest["paths"]]

    before_restore = capture_state(repo, evidence_dir, selected)
    restore_manifest(repo, evidence_dir, pass_hash)
    restored = capture_state(repo, evidence_dir, selected)
    passed = all(
        (
            same_session,
            verifier_events_match,
            results_match,
            mutation_observed,
            same_git_base,
            same_captured_paths,
            before_restore["manifest_hash"] == fail_hash,
            restored["manifest_hash"] == pass_hash,
            restored["git_base"] == pass_manifest["git_base"],
        )
    )
    report = {
        "before_restore_manifest_hash": before_restore["manifest_hash"],
        "captured_paths_match": same_captured_paths,
        "claim_scope": "captured_repository_scope",
        "evidence": {
            "fail_post_event": evidence_reference(evidence_dir, args.fail_post_event),
            "fail_pre_event": evidence_reference(evidence_dir, args.fail_pre_event),
            "fail_result_marker": evidence_reference(
                evidence_dir, args.fail_result_marker
            ),
            "mutation_event": evidence_reference(evidence_dir, args.mutation_event),
            "pass_post_event": evidence_reference(evidence_dir, args.pass_post_event),
            "pass_pre_event": evidence_reference(evidence_dir, args.pass_pre_event),
            "pass_result_marker": evidence_reference(
                evidence_dir, args.pass_result_marker
            ),
        },
        "excluded": [{"path": ".env", "status": "excluded_by_policy"}],
        "failing_manifest_hash": fail_hash,
        "git_base": pass_manifest["git_base"],
        "git_base_matches": same_git_base,
        "mutation_observed_between_results": mutation_observed,
        "passing_manifest_hash": pass_hash,
        "restore_target_manifest_hash": pass_hash,
        "restored_manifest_hash": restored["manifest_hash"],
        "result": "pass" if passed else "fail",
        "same_session": same_session,
        "schema": PROBE_SCHEMA,
        "verifier_events_match": verifier_events_match,
        "verifier_results": {
            "fail_exit_status": fail_result.get("exit_status"),
            "pass_exit_status": pass_result.get("exit_status"),
        },
    }
    report_bytes = json.dumps(report, indent=2, sort_keys=True).encode() + b"\n"
    output = evidence_dir / "integrated-closure" / f"{time.time_ns()}-{uuid.uuid4().hex}.json"
    write_once(output, report_bytes)
    print(json.dumps({"evidence": output.name, "result": report["result"]}, sort_keys=True))
    return 0 if passed else 1


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
    executable_mode = subcommands.add_parser("executable-mode")
    executable_mode.add_argument("--repo", type=Path, required=True)
    executable_mode.add_argument("--evidence-dir", type=Path, required=True)
    executable_mode.add_argument("--non-executable-tracked", required=True)
    executable_mode.add_argument("--executable-tracked", required=True)
    executable_mode.add_argument("--selected-untracked", required=True)
    integrated = subcommands.add_parser("integrated-restore")
    integrated.add_argument("--repo", type=Path, required=True)
    integrated.add_argument("--evidence-dir", type=Path, required=True)
    integrated.add_argument("--selected-untracked", required=True)
    integrated.add_argument("--pass-pre-event", required=True)
    integrated.add_argument("--pass-post-event", required=True)
    integrated.add_argument("--pass-result-marker", required=True)
    integrated.add_argument("--mutation-event", required=True)
    integrated.add_argument("--fail-pre-event", required=True)
    integrated.add_argument("--fail-post-event", required=True)
    integrated.add_argument("--fail-result-marker", required=True)
    git_ref = subcommands.add_parser("git-ref")
    git_ref.add_argument("--repo", type=Path, required=True)
    git_ref.add_argument("--evidence-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "hook":
        return hook_command()
    if args.command == "executable-mode":
        return executable_mode_command(args)
    if args.command == "git-ref":
        return git_ref_command(args)
    if args.command == "integrated-restore":
        return integrated_restore_command(args)
    return roundtrip_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
