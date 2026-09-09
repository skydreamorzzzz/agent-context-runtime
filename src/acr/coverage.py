"""Reproducible offline duplicate-read coverage scan for one pinned archive."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from acr.adapters.multi_swe_bench import ADAPTER_VERSION, AdaptedTrajectory, adapt_trajectory
from acr.candidates import (
    DETECTOR_VERSION,
    DuplicateReadAssessment,
    detect_duplicate_reads,
)
from acr.contracts import ContractModel, Envelope, EvidenceRef, InformationLabel

DATASET_NAME = "ByteDance-Seed/Multi-SWE-bench_trajs"
DATASET_REVISION = "9180bb0c633e4580fc8f74629ac6a47b8582543f"
ARCHIVE_PATH = "flash/20250725_MopenHands_Qwen3-Coder-480B-A35B.zip"
REPORT_VERSION = "multi_swe_bench_duplicate_read_coverage_v1"


class CoverageReport(Envelope):
    adapter_version: str
    detector_version: str
    producer_manifest: dict[str, Any]
    source: dict[str, Any]
    capabilities: dict[str, bool]
    metrics: dict[str, Any]
    repository_distribution: list[dict[str, Any]]
    trajectory_results: list[dict[str, Any]]
    unreadable_trajectories: list[dict[str, str]]
    audit_examples: dict[str, list[dict[str, Any]]]
    verdict: Literal["GO", "NO_GO"]
    verdict_reason: str


class CoverageAudit(ContractModel):
    status: Literal["PASS", "BLOCK"]
    blocks: list[str]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _producer_manifest() -> dict[str, Any]:
    sources = [
        Path(__file__),
        Path(__file__).with_name("candidates.py"),
        Path(__file__).parent / "adapters" / "multi_swe_bench.py",
    ]
    return {
        "producer_kind": "acr_offline_duplicate_read_scanner",
        "schema_version": "1.0",
        "adapter_version": ADAPTER_VERSION,
        "detector_version": DETECTOR_VERSION,
        "source_files": {
            path.relative_to(Path(__file__).parents[2]).as_posix(): _sha256(path.read_bytes())
            for path in sources
        },
    }


def _producer_ref(manifest: dict[str, Any]) -> EvidenceRef:
    return EvidenceRef(
        blob_hash=_sha256(_canonical_json(manifest)),
        source_id="acr_offline_duplicate_read_scanner",
        trajectory_key=f"{DETECTOR_VERSION}|{ADAPTER_VERSION}",
        locator="/producer_manifest",
        labels=[InformationLabel(scope="analysis")],
    )


def _archive_ref(source: dict[str, Any]) -> EvidenceRef:
    return EvidenceRef(
        blob_hash=source["archive_sha256"],
        source_id=DATASET_NAME,
        trajectory_key=source["dataset_revision"],
        locator=f"/{source['archive_path']}",
        labels=[InformationLabel(scope="analysis")],
    )


def _validate_source(source: dict[str, Any], archive: Path) -> list[str]:
    blocks: list[str] = []
    required = {
        "dataset_name": DATASET_NAME,
        "dataset_revision": DATASET_REVISION,
        "archive_path": ARCHIVE_PATH,
        "adapter_version": ADAPTER_VERSION,
    }
    for field, expected in required.items():
        if source.get(field) != expected:
            blocks.append(f"source_{field}_mismatch")
    try:
        raw = archive.read_bytes()
    except OSError:
        return [*blocks, "archive_unavailable"]
    if source.get("archive_size") != len(raw):
        blocks.append("archive_size_mismatch")
    if source.get("archive_sha256") != _sha256(raw):
        blocks.append("archive_hash_mismatch")
    expected_members = source.get("expected_trajectory_members")
    if not isinstance(expected_members, int) or expected_members < 1:
        blocks.append("source_member_count_invalid")
    return blocks


def _members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = []
    for item in archive.infolist():
        path = PurePosixPath(item.filename)
        if item.is_dir() or path.suffix != ".json" or "trajs" not in path.parts:
            continue
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe archive member path")
        members.append(item)
    return sorted(members, key=lambda item: item.filename)


def _trajectory_id(member: zipfile.ZipInfo) -> str:
    return PurePosixPath(member.filename).parent.name


def _assessment_counts(assessments: list[DuplicateReadAssessment]) -> dict[str, Any]:
    exact = [item for item in assessments if item.exact_output]
    strict = [item for item in assessments if item.status == "candidate"]
    return {
        "repeated_same_path_read_count": len(assessments),
        "exact_content_duplicate_count": len(exact),
        "strict_candidate_count": len(strict),
        "duplicate_read_bytes": sum(item.duplicate_bytes or 0 for item in exact),
        "strict_candidate_removable_bytes": sum(item.duplicate_bytes or 0 for item in strict),
        "rejected_count": sum(item.status == "rejected" for item in assessments),
        "unknown_count": sum(item.status == "unknown" for item in assessments),
        "exact_stage_distribution": dict(sorted(Counter(item.stage for item in exact).items())),
        "candidate_stage_distribution": dict(
            sorted(Counter(item.stage for item in strict).items())
        ),
        "reason_counts": dict(sorted(Counter(item.reason for item in assessments).items())),
    }


def _example(item: DuplicateReadAssessment, member: str, raw_hash: str) -> dict[str, Any]:
    value = item.model_dump(mode="json")
    value["artifact_member"] = member
    value["trajectory_raw_sha256"] = raw_hash
    return value


def scan_archive(archive_path: Path, source: dict[str, Any]) -> CoverageReport:
    """Scan all JSON trajectories in the exact pinned archive, without extraction."""

    source_blocks = _validate_source(source, archive_path)
    if source_blocks:
        raise ValueError(",".join(source_blocks))
    adapted: list[tuple[str, str, AdaptedTrajectory, list[DuplicateReadAssessment]]] = []
    unreadable: list[dict[str, str]] = []
    with zipfile.ZipFile(archive_path) as archive:
        members = _members(archive)
        if len(members) != source["expected_trajectory_members"]:
            raise ValueError("archive_member_count_mismatch")
        for member in members:
            raw = archive.read(member)
            trajectory_id = _trajectory_id(member)
            try:
                trajectory = adapt_trajectory(raw, trajectory_id)
                assessments = detect_duplicate_reads(
                    trajectory.read_occurrences,
                    trajectory.changes,
                    event_count=trajectory.event_count,
                )
            except (TypeError, ValueError) as exc:
                unreadable.append({"artifact_member": member.filename, "reason": str(exc)})
                continue
            adapted.append((member.filename, _sha256(raw), trajectory, assessments))

    per_trajectory: list[dict[str, Any]] = []
    all_assessments: list[tuple[str, str, DuplicateReadAssessment]] = []
    repo_totals: dict[str, Counter[str]] = defaultdict(Counter)
    input_tokens = 0
    input_usage_complete_trajectories = 0
    unsupported_reads = 0
    full_exact_duplicates = 0
    exact_intervening_change_pairs = 0
    exact_intervening_change_events = 0
    for member, raw_hash, trajectory, assessments in adapted:
        counts = _assessment_counts(assessments)
        read_by_id = {item.occurrence_id: item for item in trajectory.read_occurrences}
        exact = [item for item in assessments if item.exact_output]
        full_exact_duplicates += sum(
            read_by_id[item.older_occurrence].complete is True
            and read_by_id[item.newer_occurrence].complete is True
            for item in exact
        )
        for item in exact:
            change_count = sum(
                change.kind in {"write", "edit", "file_change"}
                and change.normalized_path == item.normalized_path
                for change in item.intervening_events
            )
            if change_count:
                exact_intervening_change_pairs += 1
                exact_intervening_change_events += change_count
        row = {
            "trajectory_id": trajectory.trajectory_id,
            "task_id": trajectory.task_id,
            "repository": trajectory.repository,
            "artifact_member": member,
            "raw_sha256": raw_hash,
            "event_count": trajectory.event_count,
            "file_read_count": len(trajectory.read_occurrences),
            "unsupported_read_count": trajectory.unsupported_read_count,
            "observed_input_tokens": trajectory.observed_input_tokens,
            "input_usage_complete": trajectory.input_usage_complete,
            **counts,
        }
        per_trajectory.append(row)
        all_assessments.extend((member, raw_hash, item) for item in assessments)
        repository = repo_totals[trajectory.repository]
        repository["trajectories"] += 1
        repository["file_reads"] += len(trajectory.read_occurrences)
        repository["repeated_same_path_reads"] += counts["repeated_same_path_read_count"]
        repository["exact_content_duplicates"] += counts["exact_content_duplicate_count"]
        repository["strict_candidates"] += counts["strict_candidate_count"]
        unsupported_reads += trajectory.unsupported_read_count
        if trajectory.input_usage_complete and trajectory.observed_input_tokens is not None:
            input_usage_complete_trajectories += 1
            input_tokens += trajectory.observed_input_tokens

    repeated = [item for _, _, item in all_assessments]
    exact = [item for item in repeated if item.exact_output]
    strict = [item for item in repeated if item.status == "candidate"]
    metrics = {
        "total_trajectories": len(per_trajectory) + len(unreadable),
        "total_readable_trajectories": len(per_trajectory),
        "total_file_read_occurrences": sum(row["file_read_count"] for row in per_trajectory),
        "unsupported_read_occurrences": unsupported_reads,
        "trajectories_with_repeated_same_path_read": sum(
            row["repeated_same_path_read_count"] > 0 for row in per_trajectory
        ),
        "trajectories_with_exact_content_duplicate_read": sum(
            row["exact_content_duplicate_count"] > 0 for row in per_trajectory
        ),
        "trajectories_with_strict_candidate": sum(
            row["strict_candidate_count"] > 0 for row in per_trajectory
        ),
        "repeated_same_path_read_count": len(repeated),
        "exact_content_duplicate_count": len(exact),
        "exact_complete_output_duplicate_count": full_exact_duplicates,
        "strict_candidate_count": len(strict),
        "candidate_count_per_trajectory": (
            len(strict) / len(per_trajectory) if per_trajectory else None
        ),
        "duplicate_read_bytes": sum(item.duplicate_bytes or 0 for item in exact),
        "strict_candidate_removable_bytes": sum(item.duplicate_bytes or 0 for item in strict),
        "exact_duplicates_with_intervening_file_change": exact_intervening_change_pairs,
        "intervening_file_change_event_count": exact_intervening_change_events,
        "rejected_because_intervening_change": sum(
            item.reason == "intervening_file_change" for item in repeated
        ),
        "unknown_or_unsupported_assessment_count": sum(
            item.status == "unknown" for item in repeated
        ),
        "assessment_reason_counts": dict(sorted(Counter(item.reason for item in repeated).items())),
        "exact_duplicate_stage_distribution": dict(
            sorted(Counter(item.stage for item in exact).items())
        ),
        "strict_candidate_stage_distribution": dict(
            sorted(Counter(item.stage for item in strict).items())
        ),
        "observed_input_tokens_from_embedded_provider_usage": input_tokens,
        "trajectories_with_complete_embedded_input_usage": input_usage_complete_trajectories,
        "candidate_token_estimate": None,
        "candidate_token_share": None,
        "token_estimate_reason": "exact tokenizer and actual request membership are not evidenced",
    }
    distribution = [
        {"repository": name, **dict(values)}
        for name, values in sorted(repo_totals.items())
    ]
    exact_examples = [item for item in all_assessments if item[2].exact_output][:3]
    rejection_priority = {
        "intervening_file_change": 0,
        "incomplete_read": 1,
        "output_content_changed": 2,
    }
    rejected_examples = sorted(
        (item for item in all_assessments if item[2].status == "rejected"),
        key=lambda item: (
            rejection_priority.get(item[2].reason, 9),
            item[2].trajectory_id,
            item[2].newer_source_position,
        ),
    )[:3]
    unknown_examples = [item for item in all_assessments if item[2].status == "unknown"][:3]
    strict_examples = [item for item in all_assessments if item[2].status == "candidate"][:3]
    examples = {
        "strict_positive": [_example(item, member, raw_hash) for member, raw_hash, item in strict_examples],
        "exact_duplicate_precondition": [
            _example(item, member, raw_hash) for member, raw_hash, item in exact_examples
        ],
        "rejected": [_example(item, member, raw_hash) for member, raw_hash, item in rejected_examples],
        "unknown": [_example(item, member, raw_hash) for member, raw_hash, item in unknown_examples],
    }
    capabilities = {
        "exact_tool_output_bytes": True,
        "read_occurrence_identity": True,
        "source_position": True,
        "authoritative_runtime_sequence": False,
        "exact_source_file_bytes": False,
        "source_file_encoding": False,
        "actual_request_membership": False,
        "current_file_state_check": False,
    }
    producer_manifest = _producer_manifest()
    return CoverageReport(
        kind="duplicate_read_coverage_report",
        id=REPORT_VERSION,
        producer_ref=_producer_ref(producer_manifest),
        provenance_ref=_archive_ref(source),
        adapter_version=ADAPTER_VERSION,
        detector_version=DETECTOR_VERSION,
        producer_manifest=producer_manifest,
        source=source,
        capabilities=capabilities,
        metrics=metrics,
        repository_distribution=distribution,
        trajectory_results=per_trajectory,
        unreadable_trajectories=unreadable,
        audit_examples=examples,
        verdict="NO_GO",
        verdict_reason=(
            "The archive shows exact repeated read outputs, but it does not evidence exact source-file "
            "bytes/encoding, actual request co-membership, or a current state check; zero strict legal "
            "candidates can therefore be established fail-closed."
        ),
    )


def audit_coverage_report(
    report: CoverageReport, archive_path: Path, source: dict[str, Any]
) -> CoverageAudit:
    """Re-scan the pinned raw archive and compare the complete semantic report."""

    blocks = _validate_source(source, archive_path)
    if report.producer_manifest != _producer_manifest():
        blocks.append("coverage_producer_manifest_mismatch")
    if report.producer_ref != _producer_ref(report.producer_manifest):
        blocks.append("coverage_producer_mismatch")
    if report.provenance_ref != _archive_ref(source):
        blocks.append("coverage_source_ref_mismatch")
    if report.source != source:
        blocks.append("coverage_source_manifest_mismatch")
    if not blocks:
        try:
            rebuilt = scan_archive(archive_path, source)
            if _canonical_json(rebuilt.model_dump(mode="json")) != _canonical_json(
                report.model_dump(mode="json")
            ):
                blocks.append("coverage_report_mismatch")
        except (OSError, TypeError, ValueError, zipfile.BadZipFile):
            blocks.append("coverage_rescan_failed")
    return CoverageAudit(status="BLOCK" if blocks else "PASS", blocks=sorted(set(blocks)))


def render_coverage_markdown(report: CoverageReport, audit: CoverageAudit) -> str:
    """Render a concise human report without adding causal effectiveness claims."""

    metrics = report.metrics
    total = metrics["total_readable_trajectories"]
    repeat_pct = 100 * metrics["trajectories_with_repeated_same_path_read"] / total if total else 0
    exact_pct = (
        100 * metrics["trajectories_with_exact_content_duplicate_read"] / total if total else 0
    )
    return f"""# Multi-SWE-bench Flash duplicate-read coverage audit

## Source and audit

- Dataset: `{report.source['dataset_name']}`
- Revision: `{report.source['dataset_revision']}`
- Artifact: `{report.source['archive_path']}`
- Archive SHA256: `{report.source['archive_sha256']}`
- Adapter: `{report.adapter_version}`
- Detector: `{report.detector_version}`
- Reproducibility audit: **{audit.status}**

The pinned archive contains {metrics['total_trajectories']} JSON trajectories; {total} were readable.
This is the archive actually scanned, not an assumption that every advertised Flash task is present.

Re-run from a local copy of the pinned archive:

```bash
acr scan-duplicate-reads \\
  --archive data/mswe_duplicate_read_audit/20250725_MopenHands_Qwen3-Coder-480B-A35B.zip \\
  --source-manifest configs/multi_swe_bench_flash_coverage.json \\
  --output docs/coverage/multi-swe-bench-flash-duplicate-read-v1.json \\
  --report docs/coverage/multi-swe-bench-flash-duplicate-read-v1.md
```

## Coverage

| Measure | Result |
| --- | ---: |
| File-read occurrences | {metrics['total_file_read_occurrences']} |
| Trajectories with repeated same-path reads | {metrics['trajectories_with_repeated_same_path_read']} / {total} ({repeat_pct:.1f}%) |
| Repeated same-path read occurrences | {metrics['repeated_same_path_read_count']} |
| Trajectories with exact duplicate read output | {metrics['trajectories_with_exact_content_duplicate_read']} / {total} ({exact_pct:.1f}%) |
| Exact duplicate read outputs | {metrics['exact_content_duplicate_count']} |
| Exact duplicates reported as complete output | {metrics['exact_complete_output_duplicate_count']} |
| Exact duplicate output bytes | {metrics['duplicate_read_bytes']} |
| Strict legal candidates | {metrics['strict_candidate_count']} |
| Strict removable bytes | {metrics['strict_candidate_removable_bytes']} |
| Exact duplicates with an intervening same-path edit | {metrics['exact_duplicates_with_intervening_file_change']} |

Candidate token estimate/share are **unknown**: {metrics['token_estimate_reason']}.

## Evidence limits

The event list proves distinct read occurrences, source positions, paths, and exact recorded tool-output
strings. It does not prove authoritative runtime sequence, exact original file bytes/encoding, the two
results' simultaneous membership in an actual outbound request, or a pre-send current-file state check.
Those missing facts are not defaulted to success. Shell `run` actions between reads are treated as
unresolved possible changes rather than parsed heuristically.

`exact_duplicate_precondition` examples in the machine artifact are not strict candidates. The strict
positive list is empty because no candidate passes the frozen evidence predicate.

## Decision: {report.verdict}

{report.verdict_reason}

This result measures prevalence and theoretical duplicate output bytes only. It does **not** establish
quality preservation, API cost savings, behavioral rebound, extra reads/tests/retries, or intervention
effectiveness. The next justified evidence step is native/request-level capture on a bounded workload,
not a formal deletion paired run based solely on this archive.
"""
