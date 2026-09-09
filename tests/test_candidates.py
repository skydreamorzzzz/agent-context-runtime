"""Frozen exact duplicate-read detector semantics."""

from __future__ import annotations

from acr.candidates import (
    ChangeOccurrence,
    ReadOccurrence,
    assess_duplicate_pair,
    detect_duplicate_reads,
)
from acr.contracts import EvidenceRef, InformationLabel


def _ref(position: int) -> EvidenceRef:
    return EvidenceRef(
        blob_hash="a" * 64,
        source_id="fixture",
        trajectory_key="trajectory-1",
        locator=f"/events/{position}/content",
        labels=[InformationLabel(scope="analysis")],
    )


def _read(
    position: int,
    *,
    path: str = "target.py",
    digest: str = "a" * 64,
    complete: bool | None = True,
    encoding: str | None = "utf-8",
    occurrence_id: str | None = None,
    ref: EvidenceRef | None = None,
) -> ReadOccurrence:
    return ReadOccurrence(
        trajectory_id="trajectory-1",
        occurrence_id=occurrence_id or f"read-{position}",
        source_position=position,
        result_position=position + 1,
        normalized_path=path,
        output_sha256=digest,
        output_bytes=24,
        file_sha256=digest,
        complete=complete,
        encoding=encoding,
        request_membership_observed=True,
        current_file_sha256=digest,
        evidence_refs=[ref or _ref(position)],
    )


def test_two_distinct_exact_complete_reads_are_a_candidate() -> None:
    assessments = detect_duplicate_reads([_read(1), _read(5)], [], event_count=10)
    assert len(assessments) == 1
    assert assessments[0].status == "candidate"
    assert assessments[0].reason == "strict_exact_duplicate"
    assert assessments[0].older_occurrence != assessments[0].newer_occurrence


def test_path_or_content_difference_is_rejected() -> None:
    path = assess_duplicate_pair(_read(1), _read(5, path="other.py"), [], event_count=10)
    content = assess_duplicate_pair(
        _read(1), _read(5, digest="b" * 64), [], event_count=10
    )
    assert (path.status, path.reason) == ("rejected", "path_mismatch")
    assert (content.status, content.reason) == ("rejected", "output_content_changed")


def test_repeated_reference_to_one_read_is_not_a_second_occurrence() -> None:
    shared = _ref(1)
    assessment = assess_duplicate_pair(
        _read(1, ref=shared),
        _read(5, ref=shared),
        [],
        event_count=10,
    )
    assert (assessment.status, assessment.reason) == ("rejected", "same_occurrence")


def test_intervening_change_and_incomplete_read_are_rejected() -> None:
    change = ChangeOccurrence(
        occurrence_id="edit-3",
        source_position=3,
        kind="edit",
        normalized_path="target.py",
        evidence_refs=[_ref(3)],
    )
    changed = assess_duplicate_pair(_read(1), _read(5), [change], event_count=10)
    incomplete = assess_duplicate_pair(
        _read(1), _read(5, complete=False), [], event_count=10
    )
    assert (changed.status, changed.reason) == ("rejected", "intervening_file_change")
    assert (incomplete.status, incomplete.reason) == ("rejected", "incomplete_read")


def test_missing_key_evidence_fails_closed_as_unknown() -> None:
    older = _read(1, encoding=None)
    newer = _read(5, encoding=None)
    assessment = assess_duplicate_pair(older, newer, [], event_count=10)
    assert assessment.status == "unknown"
    assert assessment.reason == "file_encoding_unobserved"
