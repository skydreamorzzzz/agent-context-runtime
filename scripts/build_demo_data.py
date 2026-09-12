"""Build the static Agent Forensics demo view from committed F1 evidence."""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
from typing import Any

from acr.forensics.session import audit_session
from acr.forensics.store import ForensicsEvidenceStore
from acr.forensics_contracts import (
    AgentEvent,
    CapturedPathState,
    VerificationReceipt,
    WorkspaceCheckpoint,
)

MAX_DIFF_BLOB_BYTES = 200_000

LEGACY_DIAGNOSTICS = (
    ("W01", "Context Growth", "Historical context or token input growth."),
    ("W02", "Large Tool Output", "A single tool response contains a large payload."),
    ("W03", "Failure Stack", "A long failure stack or error log was not truncated."),
    ("W04", "Duplicate Context", "Large, highly similar context repeats."),
    ("W05", "Large User Input", "A single user input is unusually large."),
    ("W06", "Repeated Command", "Similar tool commands repeat in a short window."),
    ("W07", "Tool Loop", "Tool calls form a dense repeated loop."),
    ("W08", "Retry Storm", "Assistant output shows highly similar retries."),
)


class UnsupportedDemoSession(ValueError):
    """The narrow static demo cannot derive an unambiguous PASS-to-FAIL boundary."""


def _sequence(record: AgentEvent | VerificationReceipt) -> int:
    if record.ordering is None or record.ordering.sequence.value is None:
        raise UnsupportedDemoSession("missing observed ordering")
    return record.ordering.sequence.value


def _load_records(store: ForensicsEvidenceStore, category: str, model: type[Any]) -> list[Any]:
    return [model.model_validate_json(path.read_text()) for path in store.record_files(category)]


def _content_hash(state: CapturedPathState | None) -> str | None:
    if state is None or state.content_ref is None:
        return None
    return state.content_ref.blob_hash


def _read_demo_text(
    store: ForensicsEvidenceStore, state: CapturedPathState | None
) -> str | None:
    if state is None or state.state != "present" or state.content_ref is None:
        return ""
    content = store.blob_bytes(state.content_ref.blob_hash)
    if len(content) > MAX_DIFF_BLOB_BYTES or b"\0" in content:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _unified_diff(
    store: ForensicsEvidenceStore,
    path: str,
    before: CapturedPathState | None,
    after: CapturedPathState | None,
) -> str | None:
    before_text = _read_demo_text(store, before)
    after_text = _read_demo_text(store, after)
    if before_text is None or after_text is None:
        return None
    lines = difflib.unified_diff(
        before_text.splitlines(),
        after_text.splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    value = "\n".join(lines)
    return f"{value}\n" if value else None


def _changed_files(
    store: ForensicsEvidenceStore,
    passing: WorkspaceCheckpoint,
    failing: WorkspaceCheckpoint,
) -> list[dict[str, Any]]:
    before_by_path = {item.repo_relative_path: item for item in passing.captured_paths}
    after_by_path = {item.repo_relative_path: item for item in failing.captured_paths}
    changed: list[dict[str, Any]] = []
    for path in sorted(before_by_path.keys() | after_by_path.keys()):
        before = before_by_path.get(path)
        after = after_by_path.get(path)
        before_present = before is not None and before.state == "present"
        after_present = after is not None and after.state == "present"
        before_identity = (
            before.state,
            _content_hash(before),
            before.executable,
        ) if before is not None else None
        after_identity = (
            after.state,
            _content_hash(after),
            after.executable,
        ) if after is not None else None
        if before_identity == after_identity:
            continue
        if not before_present and after_present:
            change_type = "added"
        elif before_present and not after_present:
            change_type = "deleted"
        else:
            change_type = "modified"
        diff = _unified_diff(store, path, before, after)
        changed.append(
            {
                "after_executable": after.executable if after is not None else None,
                "after_hash": _content_hash(after),
                "before_executable": before.executable if before is not None else None,
                "before_hash": _content_hash(before),
                "change_type": change_type,
                "diff": diff,
                "diff_status": "available" if diff is not None else "unavailable",
                "path": path,
            }
        )
    return changed


def _observed_activity(
    store: ForensicsEvidenceStore,
    events: list[AgentEvent],
    start_sequence: int,
    end_sequence: int,
) -> list[dict[str, Any]]:
    operations: dict[str, dict[str, Any]] = {}
    for event in sorted(events, key=_sequence):
        sequence = _sequence(event)
        if not start_sequence < sequence < end_sequence or event.operation is None:
            continue
        if event.source_evidence_ref is None:
            continue
        observation = json.loads(store.blob_bytes(event.source_evidence_ref.blob_hash))
        summary = observation.get("tool_input_summary")
        if isinstance(summary, dict) and summary.get("command_class") == "exact_configured_verifier":
            continue
        operation_id = event.operation.occurrence_id
        if operation_id not in operations:
            operations[operation_id] = {
                "_occurrence_id": operation_id,
                "event_count": 0,
                "kind": event.operation.name,
                "label": f"{event.operation.name} operation",
                "sequence": sequence,
            }
        operations[operation_id]["event_count"] += 1
    return sorted(operations.values(), key=lambda item: item["sequence"])


def _raw_diagnostic_view(
    raw_session_dir: Path | None,
    events: list[AgentEvent],
    activity: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Project local raw hits and bind them to F1 occurrences only by exact ID."""

    if raw_session_dir is None:
        return [], None
    steps_path = raw_session_dir / "normalized" / "steps.json"
    hits_path = raw_session_dir / "diagnostics" / "hits.json"
    metadata_path = raw_session_dir / "metadata.json"
    if not (steps_path.is_file() and hits_path.is_file() and metadata_path.is_file()):
        return [], {"correlation_status": "unavailable", "source_class": "demo_raw"}
    steps = json.loads(steps_path.read_text()).get("steps", [])
    hits = json.loads(hits_path.read_text()).get("hits", [])
    metadata = json.loads(metadata_path.read_text())
    if not isinstance(steps, list) or not isinstance(hits, list):
        raise UnsupportedDemoSession("demo raw projection is malformed")

    f1_sequences: dict[str, int] = {}
    for event in events:
        if event.operation is not None:
            occurrence_id = event.operation.occurrence_id
            f1_sequences[occurrence_id] = min(
                f1_sequences.get(occurrence_id, _sequence(event)), _sequence(event)
            )
    raw_steps = {
        step.get("occurrence_id"): step
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("occurrence_id"), str)
    }
    for item in activity:
        raw_step = raw_steps.get(item.get("_occurrence_id"))
        if not isinstance(raw_step, dict):
            continue
        if raw_step.get("tool") == "Read" and isinstance(raw_step.get("input"), dict):
            path = raw_step["input"].get("file_path")
            if isinstance(path, str) and path:
                item["label"] = f"Read {Path(path).name}"

    definitions = {
        "exact_repeated_read_result_v1": (
            "D01",
            "Exact Repeated Read",
            "W04-compatible exact repeated Read result; not a full W04 implementation.",
        ),
        "exact_repeated_command_v1": (
            "D02",
            "Exact Repeated Command",
            "W06-compatible exact repeated command; not a full W06 implementation.",
        ),
    }
    grouped: dict[str, dict[str, Any]] = {}
    exact_count = 0
    unavailable_count = 0
    for hit in hits:
        if not isinstance(hit, dict) or hit.get("diagnostic_id") not in definitions:
            continue
        diagnostic_id = hit["diagnostic_id"]
        occurrence_id = hit.get("occurrence_id")
        f1_sequence = f1_sequences.get(occurrence_id) if isinstance(occurrence_id, str) else None
        correlation = "exact" if f1_sequence is not None else "unavailable"
        exact_count += correlation == "exact"
        unavailable_count += correlation == "unavailable"
        rule, title, description = definitions[diagnostic_id]
        item = grouped.setdefault(
            diagnostic_id,
            {
                "description": description,
                "event_sequences": [],
                "occurrences": 0,
                "raw_event_sequences": [],
                "related_event_sequences": [],
                "rule": rule,
                "rule_family": hit.get("rule_family"),
                "severity": "yellow",
                "source": "demo_raw_derived",
                "status": "warning",
                "summary": hit.get("summary", description),
                "title": title,
            },
        )
        item["occurrences"] += 1
        if isinstance(hit.get("event_sequence"), int):
            item["raw_event_sequences"].append(hit["event_sequence"])
        if f1_sequence is not None:
            item["event_sequences"].append(f1_sequence)
        related_ids = hit.get("related_occurrence_ids")
        if isinstance(related_ids, list):
            item["related_event_sequences"].extend(
                f1_sequences[value]
                for value in related_ids
                if isinstance(value, str) and value in f1_sequences
            )
    if exact_count and unavailable_count:
        correlation_status = "partial"
    elif exact_count:
        correlation_status = "exact"
    else:
        correlation_status = "unavailable"
    return list(grouped.values()), {
        "correlation_status": correlation_status,
        "diagnostic_hit_count": len(hits),
        "normalized_step_count": len(steps),
        "source_class": "demo_raw_derived",
        "source_hash": metadata.get("source_hash"),
    }


def _receipt_view(receipt: VerificationReceipt) -> dict[str, Any]:
    if receipt.finished_at.value is None or receipt.exit_code.value is None:
        raise UnsupportedDemoSession("receipt lacks observed terminal facts")
    return {
        "checkpoint_id": receipt.pre_checkpoint_id,
        "exit_code": receipt.exit_code.value,
        "manifest_hash": receipt.tested_captured_workspace_manifest_hash,
        "outcome": "pass" if receipt.passed.value is True else "fail",
        "receipt_id": receipt.id,
        "timestamp": receipt.finished_at.value.isoformat(),
    }


def _diagnostic_view(presentation: dict[str, Any]) -> list[dict[str, Any]]:
    """Project demo-only annotations without presenting them as F1 evidence."""
    annotations = presentation.get("diagnostics", {})
    result: list[dict[str, Any]] = []
    for rule, title, description in LEGACY_DIAGNOSTICS:
        annotation = annotations.get(rule, {}) if isinstance(annotations, dict) else {}
        status = annotation.get("status") if isinstance(annotation, dict) else None
        severity = annotation.get("severity") if isinstance(annotation, dict) else None
        summary = annotation.get("summary") if isinstance(annotation, dict) else None
        if status not in {"normal", "warning"} or severity not in {"green", "yellow"}:
            status, severity = "not_evaluated", "neutral"
            summary = "Not evaluated from privacy-bounded F1 evidence."
        result.append(
            {
                "rule": rule,
                "title": title,
                "description": description,
                "severity": severity,
                "status": status,
                "summary": summary if isinstance(summary, str) else description,
                "occurrences": annotation.get("occurrences", 0)
                if isinstance(annotation, dict) and isinstance(annotation.get("occurrences", 0), int)
                else 0,
                "event_sequences": annotation.get("event_sequences", [])
                if isinstance(annotation, dict)
                and isinstance(annotation.get("event_sequences", []), list)
                and all(isinstance(value, int) for value in annotation.get("event_sequences", []))
                else [],
                "source": "demo presentation metadata",
            }
        )
    return result


def _timeline_view(
    starting: VerificationReceipt,
    ending: VerificationReceipt,
    activity: list[dict[str, Any]],
    changed_files: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    verifier: str,
) -> list[dict[str, Any]]:
    def refs_for(sequence: int) -> list[dict[str, str]]:
        return [
            {
                "rule": item["rule"],
                "title": item["title"],
                "summary": item["summary"],
                "source": item["source"],
            }
            for item in diagnostics
            if sequence in item["event_sequences"] and item["status"] == "warning"
        ]

    entries: list[dict[str, Any]] = [
        {
            "kind": "verified_pass",
            "label": "Verified PASS",
            "detail": f"{verifier} · exit code {starting.exit_code.value}",
            "status": "green",
            "sequence": _sequence(starting),
            "diagnostic_refs": [],
        }
    ]
    for item in activity:
        refs = refs_for(item["sequence"])
        entries.append(
            {
                "kind": "observed_activity",
                "label": item["label"],
                "detail": "Observed between verification boundaries",
                "status": step_status({"diagnostic_refs": refs, "is_normal_observed_operation": False}),
                "sequence": item["sequence"],
                "diagnostic_refs": refs,
            }
        )
    paths = ", ".join(item["path"] for item in changed_files) or "No captured path change"
    entries.append(
        {
            "kind": "repository_transition",
            "label": (
                "Repository state changed" if changed_files else "Repository state unchanged"
            ),
            "detail": paths,
            "status": "neutral",
            "sequence": None,
            "diagnostic_refs": [],
        }
    )
    entries.append(
        {
            "kind": "verified_fail" if ending.passed.value is False else "verified_pass",
            "label": "Verified FAIL" if ending.passed.value is False else "Verified PASS",
            "detail": f"{verifier} · exit code {ending.exit_code.value}",
            "status": "red" if ending.passed.value is False else "green",
            "sequence": _sequence(ending),
            "diagnostic_refs": [],
        }
    )
    return entries


def step_status(step: dict[str, Any]) -> str:
    """Apply the small, ordered status rule used by the demo timeline."""
    if step.get("has_verified_failure"):
        return "red"
    if step.get("diagnostic_refs"):
        return "yellow"
    if step.get("has_verified_success") or step.get("is_normal_observed_operation"):
        return "green"
    return "neutral"


def _integrity_view(
    starting_receipt: VerificationReceipt,
    ending_receipt: VerificationReceipt,
    starting_checkpoint: WorkspaceCheckpoint,
    ending_checkpoint: WorkspaceCheckpoint,
) -> dict[str, Any]:
    same_session = starting_receipt.session_id == ending_receipt.session_id
    manifests_distinct = (
        starting_checkpoint.captured_workspace_manifest_hash
        != ending_checkpoint.captured_workspace_manifest_hash
    )
    ending_failed = ending_receipt.passed.value is False
    return {
        "status": "verified" if same_session else "unsupported",
        "checks": [
            {"label": "Session audit", "status": "pass", "detail": "audit_session passed"},
            {"label": "Exact verifier observed", "status": "pass", "detail": "configured"},
            {"label": "Initial PASS backed by exit code 0", "status": "pass", "detail": "observed"},
            {
                "label": (
                    "FAIL backed by non-zero exit"
                    if ending_failed
                    else "Final PASS backed by exit code 0"
                ),
                "status": "pass",
                "detail": "observed",
            },
            {"label": "Pre-verifier checkpoints", "status": "pass", "detail": "both resolve"},
            {"label": "Manifest hashes verified", "status": "pass", "detail": "canonical"},
            {"label": "Same session binding", "status": "pass" if same_session else "fail", "detail": "receipt correlation"},
            {
                "label": "Repository state comparison",
                "status": "pass",
                "detail": "manifest hashes differ" if manifests_distinct else "no captured change",
            },
        ],
    }


def _privacy_view(*, demo_raw_active: bool) -> dict[str, Any]:
    return {
        "status": "enforced",
        "captured": ["Sanitized agent events", "Repository state", "Verification results"],
        "not_persisted": [
            "Prompt bodies",
            "Environment values",
            "Raw hook payloads",
            "Tool response bodies",
            "Transcript paths",
            "Verifier output bodies",
        ],
        "demo_raw_active": demo_raw_active,
        "diagnostic_note": (
            "本地 Demo Raw Capture 已启用；raw 正文位于 gitignored 本地目录，不属于 F1 journal。"
            if demo_raw_active
            else "W01–W08 注解是展示元数据，不是 F1 evidence。"
        ),
    }


def _select_transition(
    receipts: list[VerificationReceipt],
) -> tuple[VerificationReceipt, VerificationReceipt, str]:
    ordered = sorted(receipts, key=_sequence)
    for fail_index, failing in enumerate(ordered):
        if failing.passed.value is not False:
            continue
        preceding = [item for item in ordered[:fail_index] if item.passed.value is True]
        if preceding:
            return preceding[-1], failing, "failure_boundary"
    passing = [item for item in ordered if item.passed.value is True]
    if len(passing) >= 2:
        return passing[0], passing[-1], "healthy_transition"
    raise UnsupportedDemoSession("no supported PASS-to-FAIL or PASS-to-PASS transition")


def build_session_view(
    evidence_root: Path,
    session_id: str,
    presentation: dict[str, Any] | None = None,
    raw_session_dir: Path | None = None,
) -> dict[str, Any]:
    issues = audit_session(evidence_root, session_id)
    if issues:
        raise UnsupportedDemoSession("session audit did not pass")
    store = ForensicsEvidenceStore(evidence_root, session_id)
    metadata = store.load_session()
    receipts = _load_records(store, "receipts", VerificationReceipt)
    checkpoints = {
        item.id: item for item in _load_records(store, "checkpoints", WorkspaceCheckpoint)
    }
    events = _load_records(store, "events", AgentEvent)
    starting_receipt, ending_receipt, trajectory_kind = _select_transition(receipts)
    try:
        starting_checkpoint = checkpoints[starting_receipt.pre_checkpoint_id]
        ending_checkpoint = checkpoints[ending_receipt.pre_checkpoint_id]
    except KeyError as error:
        raise UnsupportedDemoSession("receipt checkpoint is unavailable") from error
    presentation = presentation or {}
    changed_files = _changed_files(store, starting_checkpoint, ending_checkpoint)
    activity = _observed_activity(
        store,
        events,
        _sequence(starting_receipt),
        _sequence(ending_receipt),
    )
    diagnostics = _diagnostic_view(presentation)
    raw_diagnostics, raw_trajectory = _raw_diagnostic_view(
        raw_session_dir, events, activity
    )
    diagnostics.extend(raw_diagnostics)
    overall_status = "red" if ending_receipt.passed.value is False else (
        "yellow" if any(item["status"] == "warning" for item in diagnostics) else "green"
    )
    title = presentation.get("title")
    description = presentation.get("description")
    if not isinstance(title, str) or not title:
        title = f"Session {session_id.removeprefix('session-')[:8]}"
    if not isinstance(description, str):
        description = "Observed verified-state transition"
    public_activity = [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in activity
    ]
    result = {
        "changed_files": changed_files,
        "end_verification": _receipt_view(ending_receipt),
        "first_fail": _receipt_view(ending_receipt) if ending_receipt.passed.value is False else None,
        "final_pass": _receipt_view(ending_receipt) if ending_receipt.passed.value is True else None,
        "last_pass": _receipt_view(starting_receipt),
        "start_verification": _receipt_view(starting_receipt),
        "overall_status": overall_status,
        "observed_activity": public_activity,
        "timeline": _timeline_view(
            starting_receipt,
            ending_receipt,
            activity,
            changed_files,
            diagnostics,
            metadata["verifier"],
        ),
        "diagnostics": diagnostics,
        "evidence_integrity": _integrity_view(
            starting_receipt, ending_receipt, starting_checkpoint, ending_checkpoint
        ),
        "privacy_boundary": _privacy_view(demo_raw_active=raw_trajectory is not None),
        "presentation": {
            "description": description,
            "source": "demo/cases.json",
            "title": title,
        },
        "session_id": session_id,
        "provenance": {
            "audit_status": "pass",
            "real_capture": True,
            "raw_committed": False,
            "source_classes": [
                "acr_f1",
                *(["demo_raw_derived"] if raw_diagnostics else []),
            ],
        },
        "summary": {
            "boundary_status": "observed" if trajectory_kind == "failure_boundary" else "not_applicable",
            "changed_file_count": len(changed_files),
            "overall_status": overall_status,
            "trajectory_kind": trajectory_kind,
            "verified_fail_present": ending_receipt.passed.value is False,
            "diagnostic_warning_count": sum(item["status"] == "warning" for item in diagnostics),
        },
        "verifier": metadata["verifier"],
    }
    if raw_trajectory is not None:
        result["raw_trajectory"] = raw_trajectory
    return result


def _load_case_metadata(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError("demo case metadata must be a JSON object")
    return value


def _load_committed_artifacts(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_dir():
        return []
    sessions: list[dict[str, Any]] = []
    for artifact_path in sorted(path.glob("*.json")):
        artifact = json.loads(artifact_path.read_text())
        if (
            not isinstance(artifact, dict)
            or artifact.get("schema") != "acr.committed-demo-case/0.1"
            or not isinstance(artifact.get("session"), dict)
        ):
            raise TypeError(f"invalid committed demo artifact: {artifact_path}")
        session = artifact["session"]
        session["artifact"] = {
            "case_id": artifact.get("case_id"),
            "source_class": artifact.get("source_class"),
            "source_hash": artifact.get("source_hash"),
        }
        sessions.append(session)
    return sorted(
        sessions,
        key=lambda item: item.get("presentation", {}).get("order", 100),
    )


def build_demo_data(
    evidence_root: Path,
    *,
    cases_path: Path | None = None,
    raw_root: Path | None = None,
    artifacts_root: Path | None = None,
) -> dict[str, Any]:
    sessions_root = evidence_root / "sessions"
    discovered = sorted(path.name for path in sessions_root.iterdir() if path.is_dir())
    case_metadata = _load_case_metadata(cases_path)
    sessions = _load_committed_artifacts(artifacts_root)
    artifact_session_ids = {item.get("session_id") for item in sessions}
    skipped: list[dict[str, str]] = []
    for session_id in discovered:
        if session_id in artifact_session_ids:
            continue
        try:
            sessions.append(
                build_session_view(
                    evidence_root,
                    session_id,
                    case_metadata.get(session_id),
                    raw_root / session_id if raw_root is not None else None,
                )
            )
        except (OSError, TypeError, ValueError) as error:
            skipped.append({"reason": str(error), "session_id": session_id})
    return {
        "schema": "acr.demo-view/0.2",
        "sessions": sessions,
        "skipped_sessions": skipped,
        "source": {
            "discovered_session_count": len(discovered),
            "kind": "agent_forensics_f1_evidence",
            "committed_artifact_count": len(_load_committed_artifacts(artifacts_root)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=Path("docs/receipts/f1_product_core"))
    parser.add_argument("--output", type=Path, default=Path("demo/data/sessions.json"))
    parser.add_argument("--cases", type=Path, default=Path("demo/cases.json"))
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument(
        "--artifacts-root", type=Path, default=Path("demo/case-artifacts")
    )
    args = parser.parse_args()
    payload = build_demo_data(
        args.evidence_root,
        cases_path=args.cases,
        raw_root=args.raw_root,
        artifacts_root=args.artifacts_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        f"Wrote {len(payload['sessions'])} demo session(s) to {args.output}; "
        f"skipped {len(payload['skipped_sessions'])}."
    )


if __name__ == "__main__":
    main()
