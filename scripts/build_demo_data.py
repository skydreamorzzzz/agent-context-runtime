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
                "event_count": 0,
                "kind": event.operation.name,
                "label": f"{event.operation.name} operation",
                "sequence": sequence,
            }
        operations[operation_id]["event_count"] += 1
    return sorted(operations.values(), key=lambda item: item["sequence"])


def _receipt_view(receipt: VerificationReceipt) -> dict[str, Any]:
    if receipt.finished_at.value is None or receipt.exit_code.value is None:
        raise UnsupportedDemoSession("receipt lacks observed terminal facts")
    return {
        "checkpoint_id": receipt.pre_checkpoint_id,
        "exit_code": receipt.exit_code.value,
        "manifest_hash": receipt.tested_captured_workspace_manifest_hash,
        "receipt_id": receipt.id,
        "timestamp": receipt.finished_at.value.isoformat(),
    }


def _select_boundary(
    receipts: list[VerificationReceipt],
) -> tuple[VerificationReceipt, VerificationReceipt]:
    ordered = sorted(receipts, key=_sequence)
    for fail_index, failing in enumerate(ordered):
        if failing.passed.value is not False:
            continue
        preceding = [item for item in ordered[:fail_index] if item.passed.value is True]
        if preceding:
            return preceding[-1], failing
    raise UnsupportedDemoSession("no observed PASS-to-FAIL boundary")


def build_session_view(
    evidence_root: Path,
    session_id: str,
    presentation: dict[str, Any] | None = None,
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
    passing_receipt, failing_receipt = _select_boundary(receipts)
    try:
        passing_checkpoint = checkpoints[passing_receipt.pre_checkpoint_id]
        failing_checkpoint = checkpoints[failing_receipt.pre_checkpoint_id]
    except KeyError as error:
        raise UnsupportedDemoSession("receipt checkpoint is unavailable") from error
    changed_files = _changed_files(store, passing_checkpoint, failing_checkpoint)
    presentation = presentation or {}
    title = presentation.get("title")
    description = presentation.get("description")
    if not isinstance(title, str) or not title:
        title = f"Session {session_id.removeprefix('session-')[:8]}"
    if not isinstance(description, str):
        description = "Observed verified-state transition"
    return {
        "changed_files": changed_files,
        "first_fail": _receipt_view(failing_receipt),
        "last_pass": _receipt_view(passing_receipt),
        "observed_activity": _observed_activity(
            store,
            events,
            _sequence(passing_receipt),
            _sequence(failing_receipt),
        ),
        "presentation": {
            "description": description,
            "source": "demo/cases.json",
            "title": title,
        },
        "session_id": session_id,
        "summary": {
            "boundary_status": "observed",
            "changed_file_count": len(changed_files),
        },
        "verifier": metadata["verifier"],
    }


def _load_case_metadata(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError("demo case metadata must be a JSON object")
    return value


def build_demo_data(
    evidence_root: Path,
    *,
    cases_path: Path | None = None,
) -> dict[str, Any]:
    sessions_root = evidence_root / "sessions"
    discovered = sorted(path.name for path in sessions_root.iterdir() if path.is_dir())
    case_metadata = _load_case_metadata(cases_path)
    sessions: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for session_id in discovered:
        try:
            sessions.append(
                build_session_view(evidence_root, session_id, case_metadata.get(session_id))
            )
        except (OSError, TypeError, ValueError) as error:
            skipped.append({"reason": str(error), "session_id": session_id})
    return {
        "schema": "acr.demo-view/0.1",
        "sessions": sessions,
        "skipped_sessions": skipped,
        "source": {
            "discovered_session_count": len(discovered),
            "kind": "agent_forensics_f1_evidence",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=Path("docs/receipts/f1_product_core"))
    parser.add_argument("--output", type=Path, default=Path("demo/data/sessions.json"))
    parser.add_argument("--cases", type=Path, default=Path("demo/cases.json"))
    args = parser.parse_args()
    payload = build_demo_data(args.evidence_root, cases_path=args.cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        f"Wrote {len(payload['sessions'])} demo session(s) to {args.output}; "
        f"skipped {len(payload['skipped_sessions'])}."
    )


if __name__ == "__main__":
    main()
