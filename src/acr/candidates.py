"""Deterministic exact duplicate-read detection for offline coverage audits."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from acr.contracts import ContractModel, EvidenceRef

DETECTOR_VERSION = "exact_duplicate_complete_read_v1"


class ReadOccurrence(ContractModel):
    """The evidence that an adapter can prove about one historical read."""

    trajectory_id: str
    occurrence_id: str
    source_position: int = Field(ge=0)
    result_position: int | None = Field(default=None, ge=0)
    normalized_path: str | None = None
    output_sha256: str | None = None
    output_bytes: int | None = Field(default=None, ge=0)
    file_sha256: str | None = None
    complete: bool | None = None
    encoding: str | None = None
    request_membership_observed: bool | None = None
    current_file_sha256: str | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    unsupported_reason: str | None = None


class ChangeOccurrence(ContractModel):
    """An observed or unresolved operation between two read occurrences."""

    occurrence_id: str
    source_position: int = Field(ge=0)
    kind: Literal["write", "edit", "file_change", "unknown_change"]
    normalized_path: str | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class DuplicateReadAssessment(ContractModel):
    """One deterministic assessment of a later same-path read."""

    trajectory_id: str
    older_occurrence: str
    newer_occurrence: str
    older_source_position: int
    newer_source_position: int
    normalized_path: str
    status: Literal["candidate", "rejected", "unknown"]
    reason: str
    exact_output: bool
    duplicate_bytes: int | None = None
    stage: Literal["early", "middle", "late"]
    intervening_events: list[ChangeOccurrence]
    evidence_refs: list[EvidenceRef]


def _stage(position: int, event_count: int) -> Literal["early", "middle", "late"]:
    denominator = max(event_count, 1)
    fraction = position / denominator
    if fraction < 1 / 3:
        return "early"
    if fraction < 2 / 3:
        return "middle"
    return "late"


def _assessment(
    older: ReadOccurrence,
    newer: ReadOccurrence,
    changes: list[ChangeOccurrence],
    event_count: int,
    status: Literal["candidate", "rejected", "unknown"],
    reason: str,
) -> DuplicateReadAssessment:
    refs = [*older.evidence_refs, *newer.evidence_refs]
    return DuplicateReadAssessment(
        trajectory_id=newer.trajectory_id,
        older_occurrence=older.occurrence_id,
        newer_occurrence=newer.occurrence_id,
        older_source_position=older.source_position,
        newer_source_position=newer.source_position,
        normalized_path=newer.normalized_path or older.normalized_path or "",
        status=status,
        reason=reason,
        exact_output=(
            older.output_sha256 is not None
            and older.output_sha256 == newer.output_sha256
            and older.output_bytes == newer.output_bytes
        ),
        duplicate_bytes=newer.output_bytes if older.output_sha256 == newer.output_sha256 else None,
        stage=_stage(newer.source_position, event_count),
        intervening_events=changes,
        evidence_refs=refs,
    )


def assess_duplicate_pair(
    older: ReadOccurrence,
    newer: ReadOccurrence,
    changes: list[ChangeOccurrence],
    *,
    event_count: int,
) -> DuplicateReadAssessment:
    """Apply the frozen exact-read predicate without filling evidence gaps."""

    if older.trajectory_id != newer.trajectory_id:
        return _assessment(older, newer, changes, event_count, "rejected", "cross_trajectory")
    if older.normalized_path is None or newer.normalized_path is None:
        return _assessment(older, newer, changes, event_count, "unknown", "path_unobserved")
    if older.normalized_path != newer.normalized_path:
        return _assessment(older, newer, changes, event_count, "rejected", "path_mismatch")
    older_refs = {ref.occurrence_identity for ref in older.evidence_refs}
    newer_refs = {ref.occurrence_identity for ref in newer.evidence_refs}
    if (
        older.occurrence_id == newer.occurrence_id
        or older.source_position == newer.source_position
        or (older_refs and newer_refs and older_refs == newer_refs)
    ):
        return _assessment(older, newer, changes, event_count, "rejected", "same_occurrence")
    if older.output_sha256 is None or newer.output_sha256 is None:
        return _assessment(older, newer, changes, event_count, "unknown", "output_identity_unobserved")
    if older.output_sha256 != newer.output_sha256 or older.output_bytes != newer.output_bytes:
        return _assessment(older, newer, changes, event_count, "rejected", "output_content_changed")
    same_path_changes = [
        change
        for change in changes
        if change.normalized_path == newer.normalized_path
        and change.kind in {"write", "edit", "file_change"}
    ]
    if same_path_changes:
        return _assessment(older, newer, changes, event_count, "rejected", "intervening_file_change")
    if older.complete is False or newer.complete is False:
        return _assessment(older, newer, changes, event_count, "rejected", "incomplete_read")
    if older.complete is None or newer.complete is None:
        return _assessment(older, newer, changes, event_count, "unknown", "read_completeness_unobserved")
    if any(change.kind == "unknown_change" for change in changes):
        return _assessment(older, newer, changes, event_count, "unknown", "intervening_change_unresolved")
    if older.encoding is None or newer.encoding is None:
        return _assessment(older, newer, changes, event_count, "unknown", "file_encoding_unobserved")
    if older.encoding.lower() != "utf-8" or newer.encoding.lower() != "utf-8":
        return _assessment(older, newer, changes, event_count, "rejected", "unsupported_encoding")
    if older.file_sha256 is None or newer.file_sha256 is None:
        return _assessment(older, newer, changes, event_count, "unknown", "file_bytes_identity_unobserved")
    if older.file_sha256 != newer.file_sha256:
        return _assessment(older, newer, changes, event_count, "rejected", "file_content_changed")
    if older.request_membership_observed is False or newer.request_membership_observed is False:
        return _assessment(older, newer, changes, event_count, "rejected", "not_co_present_in_request")
    if older.request_membership_observed is None or newer.request_membership_observed is None:
        return _assessment(older, newer, changes, event_count, "unknown", "request_membership_unobserved")
    if newer.current_file_sha256 is None:
        return _assessment(older, newer, changes, event_count, "unknown", "current_file_state_unverified")
    if newer.current_file_sha256 != newer.file_sha256:
        return _assessment(older, newer, changes, event_count, "rejected", "current_file_changed")
    return _assessment(older, newer, changes, event_count, "candidate", "strict_exact_duplicate")


def detect_duplicate_reads(
    reads: list[ReadOccurrence],
    changes: list[ChangeOccurrence],
    *,
    event_count: int,
) -> list[DuplicateReadAssessment]:
    """Assess each later same-path read against its latest matching prior output."""

    ordered = sorted(reads, key=lambda item: item.source_position)
    prior_by_path: dict[str, list[ReadOccurrence]] = {}
    assessments: list[DuplicateReadAssessment] = []
    for newer in ordered:
        if newer.normalized_path is None:
            continue
        prior = prior_by_path.setdefault(newer.normalized_path, [])
        if prior:
            matching = [
                older
                for older in prior
                if older.output_sha256 is not None
                and older.output_sha256 == newer.output_sha256
                and older.output_bytes == newer.output_bytes
            ]
            older = matching[-1] if matching else prior[-1]
            intervening = [
                change
                for change in changes
                if older.source_position < change.source_position < newer.source_position
            ]
            assessments.append(
                assess_duplicate_pair(older, newer, intervening, event_count=event_count)
            )
        prior.append(newer)
    return assessments
