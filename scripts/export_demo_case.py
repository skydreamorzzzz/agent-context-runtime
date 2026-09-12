"""Export one real local capture as a safe, committed static demo artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.build_demo_data import build_session_view
except ModuleNotFoundError:  # Direct `python scripts/export_demo_case.py` execution.
    from build_demo_data import build_session_view

FORBIDDEN_KEYS = {
    "body",
    "input",
    "output",
    "prompt",
    "response",
    "tool_input",
    "tool_output",
    "transcript_path",
}


def _source_tree_hash(session_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in session_root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(session_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _assert_commit_safe(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                raise ValueError(f"raw field is forbidden in committed artifact: {path}.{key}")
            _assert_commit_safe(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_commit_safe(item, f"{path}[{index}]")
    elif isinstance(value, str) and (
        value.startswith("/home/") or "/.claude/" in value or "transcript.jsonl" in value
    ):
        raise ValueError(f"local raw path is forbidden in committed artifact: {path}")


def export_case(
    *,
    evidence_root: Path,
    raw_root: Path | None,
    session_id: str,
    case_id: str,
    title: str,
    description: str,
    order: int,
) -> dict[str, Any]:
    raw_session_dir = raw_root / session_id if raw_root is not None else None
    session = build_session_view(
        evidence_root,
        session_id,
        {"description": description, "title": title},
        raw_session_dir,
    )
    session["presentation"].update({"order": order, "source": "committed demo artifact"})
    diagnostics = [
        item for item in session["diagnostics"] if item.get("source") == "demo_raw_derived"
    ]
    if diagnostics:
        session["privacy_boundary"].update(
            {
                "demo_raw_active": False,
                "diagnostic_note": (
                    "黄色诊断由本地 demo_raw 派生；仅脱敏 artifact 已提交，raw 正文未提交。"
                ),
            }
        )
    source_class = "demo_raw_derived" if diagnostics else "acr_f1"
    source_hash = (
        session.get("raw_trajectory", {}).get("source_hash")
        if diagnostics
        else _source_tree_hash(evidence_root / "sessions" / session_id)
    )
    artifact = {
        "case_id": case_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "audit_status": "pass",
            "correlation": session.get("raw_trajectory", {}).get(
                "correlation_status", "not_applicable"
            ),
            "diagnostic_detectors": [
                "exact_repeated_read_result_v1" if item["rule"] == "D01"
                else "exact_repeated_command_v1"
                for item in diagnostics
            ],
            "raw_committed": False,
            "real_capture": True,
            "repository_diff_source": "captured F1 blobs",
            "source_session_id": session_id,
            "verifier_result_source": "F1 VerificationReceipt",
        },
        "schema": "acr.committed-demo-case/0.1",
        "session": session,
        "source_class": source_class,
        "source_hash": source_hash,
    }
    _assert_commit_safe(artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--order", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = export_case(
        evidence_root=args.evidence_root,
        raw_root=args.raw_root,
        session_id=args.session_id,
        case_id=args.case_id,
        title=args.title,
        description=args.description,
        order=args.order,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(f"Wrote committed demo artifact {args.case_id} to {args.output}")


if __name__ == "__main__":
    main()
