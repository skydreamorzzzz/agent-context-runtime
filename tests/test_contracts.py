"""M0 invariants for versioned evidence contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acr.contracts import (
    Candidate,
    ContextBlock,
    DecisionView,
    Envelope,
    EvidenceRef,
    Fact,
    FileBinding,
    FileComparison,
    InformationLabel,
    propagate_label,
)


def evidence(*, locator: str = "/events/0", blob_hash: str = "a" * 64) -> EvidenceRef:
    return EvidenceRef(
        blob_hash=blob_hash,
        source_id="native-capture",
        trajectory_key="task-1/run-1",
        locator=locator,
        labels=[InformationLabel(scope="runtime", run_id="run-1", available_seq=3)],
    )


def envelope_fields(identifier: str, kind: str) -> dict[str, object]:
    return {
        "kind": kind,
        "id": identifier,
        "producer_ref": evidence(locator="/manifest"),
        "provenance_ref": evidence(locator="/provenance/0"),
    }


def test_json_round_trip_preserves_nested_contract_fields() -> None:
    binding = FileBinding(
        repo_relative_path="a.py",
        file_sha256="b" * 64,
        encoding="utf-8",
        read_event_id="event-read-1",
        observed_seq=2,
        complete=True,
    )
    block = ContextBlock(
        **envelope_fields("block-1", "context_block"),
        request_id="request-1",
        occurrence_id="occurrence-1",
        origin_event_id="event-read-1",
        role="tool",
        type="tool_result",
        tool_call_id="tool-1",
        body_pointer="/content",
        content_hash="c" * 64,
        complete=True,
        file_binding=binding,
    )
    view = DecisionView(
        **envelope_fields("view-1", "decision_view"),
        run_id="run-1",
        cutoff_seq=3,
        request_draft_hash="d" * 64,
        blocks=[block],
        file_comparisons=[
            FileComparison(
                binding_ref=evidence(locator="/bindings/0"),
                current_file_sha256="b" * 64,
                checked_seq=3,
                status="same",
            )
        ],
        policy_version="1.0",
        labels=[InformationLabel(scope="runtime", run_id="run-1", available_seq=3)],
    )

    assert DecisionView.model_validate_json(view.model_dump_json()) == view


@pytest.mark.parametrize("value", [0, False, "", []])
def test_unknown_is_explicit_and_cannot_be_represented_by_ordinary_values(value: object) -> None:
    unknown = Fact[object](value=None, status="unknown", reason="not_captured")
    assert unknown.value is None
    assert unknown.status == "unknown"
    assert unknown != value

    with pytest.raises(ValidationError, match="unknown facts must have a null value"):
        Fact[object](value=value, status="unknown", reason="not_captured")

    with pytest.raises(ValidationError, match="unknown facts require a reason"):
        Fact[object](status="unknown")


def test_observed_facts_require_evidence() -> None:
    with pytest.raises(ValidationError, match="observed facts require evidence references"):
        Fact[int](value=123, status="observed", refs=[])

    assert Fact[int](value=123, status="observed", refs=[evidence()]).value == 123


def test_derived_facts_require_provenance_evidence() -> None:
    with pytest.raises(ValidationError, match="derived facts require evidence references"):
        Fact[int](value=123, status="derived")

    assert Fact[int](value=123, status="derived", refs=[evidence(locator="/inputs/0")]).refs


def test_same_content_has_distinct_evidence_occurrence_identity() -> None:
    first_read = evidence(locator="/events/4/payload", blob_hash="e" * 64)
    second_read = evidence(locator="/events/9/payload", blob_hash="e" * 64)

    assert first_read.blob_hash == second_read.blob_hash
    assert first_read.occurrence_identity != second_read.occurrence_identity


def test_taint_is_preserved_when_deriving_label() -> None:
    source = InformationLabel(
        scope="runtime",
        run_id="run-1",
        available_seq=2,
        taints=["future", "evaluator"],
    )
    derived = propagate_label([source, InformationLabel(scope="public")])

    assert derived.taints == ["evaluator", "future"]
    assert derived.run_id == "run-1"
    assert derived.available_seq is None


def test_not_applicable_and_unknown_remain_distinct_after_serialization() -> None:
    unknown = Fact[int](status="unknown", reason="provider_did_not_report")
    not_applicable = Fact[int](status="not_applicable")

    parsed_unknown = Fact[int].model_validate_json(unknown.model_dump_json())
    parsed_not_applicable = Fact[int].model_validate_json(not_applicable.model_dump_json())

    assert parsed_unknown.status == "unknown"
    assert parsed_unknown.reason == "provider_did_not_report"
    assert parsed_not_applicable.status == "not_applicable"
    assert parsed_not_applicable.reason is None


def test_contracts_reject_unknown_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Envelope(**envelope_fields("envelope-1", "envelope"), unexpected="not a contract field")


def test_candidate_keeps_occurrence_ids_separate_from_content_reference() -> None:
    candidate = Candidate(
        **envelope_fields("candidate-1", "candidate"),
        run_id="run-1",
        view_id="view-1",
        rule_version="omit_one_duplicate_read_v1",
        older_occurrence="block-older",
        newest_occurrence="block-newer",
        evidence_refs=[evidence(locator="/events/4"), evidence(locator="/events/9")],
        preconditions=["same_full_read", "current_file_hash_matches"],
    )

    assert candidate.older_occurrence != candidate.newest_occurrence
