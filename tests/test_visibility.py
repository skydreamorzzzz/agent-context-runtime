"""Frozen anti-cheating checks for the narrow DecisionView boundary."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from acr.contracts import (
    ContextBlock,
    Event,
    EvidenceRef,
    FileBinding,
    FileComparison,
    InformationLabel,
    propagate_label,
)
from acr.visibility import VisibilityViolation, build_view


def _ref(
    *,
    scope: str = "runtime",
    run_id: str | None = "run-1",
    available_seq: int | None = 1,
    taints: list[str] | None = None,
) -> EvidenceRef:
    return EvidenceRef(
        blob_hash="a" * 64,
        source_id="source",
        trajectory_key=run_id or "public-task",
        locator="/value",
        labels=[
            InformationLabel(
                scope=scope,
                run_id=run_id,
                available_seq=available_seq,
                taints=taints or [],
            )
        ],
    )


def _event(
    *,
    run_id: str = "run-1",
    available_seq: int | None = 1,
    kind: str = "response",
    call_id: str = "call-1",
) -> Event:
    now = datetime.now(timezone.utc)
    return Event(
        kind=kind,
        id="event:run-1:1",
        producer_ref=_ref(),
        run_id=run_id,
        event_seq=1,
        call_id=call_id,
        payload_ref=_ref(),
        available_seq=available_seq,
        start=now,
        end=now if available_seq is not None else None,
    )


def _block(ref: EvidenceRef | None = None) -> ContextBlock:
    return ContextBlock(
        kind="context_block",
        id="block-1",
        producer_ref=_ref(),
        provenance_ref=ref or _ref(),
        request_id="request-1",
        occurrence_id="request-1:block:0",
        origin_event_id="event:run-1:1",
        role="assistant",
        type="assistant_response",
        body_pointer="/messages/0/content",
        content_hash="b" * 64,
        complete=True,
    )


def _build(block: ContextBlock, event: Event | None = None):
    return build_view(
        run_id="run-1",
        cutoff_seq=2,
        request_draft_hash="c" * 64,
        blocks=[block],
        file_comparisons=[],
        events=[event or _event()],
        producer_ref=_ref(),
    )


def test_decision_view_accepts_only_a_completed_same_run_prefix() -> None:
    view = _build(_block())
    assert view.run_id == "run-1"
    assert view.cutoff_seq == 2
    assert view.blocks[0].origin_event_id == "event:run-1:1"


@pytest.mark.parametrize(
    ("ref", "event", "reason"),
    [
        (_ref(available_seq=3), _event(available_seq=1), "future_evidence"),
        (_ref(run_id="run-2"), _event(), "cross_run_evidence"),
        (_ref(scope="evaluator"), _event(), "unauthorized_scope"),
        (_ref(taints=["gold"]), _event(), "tainted_evidence"),
        (_ref(available_seq=None), _event(), "unknown_visibility"),
    ],
)
def test_decision_view_rejects_unauthorized_or_incomplete_evidence(
    ref: EvidenceRef, event: Event, reason: str
) -> None:
    with pytest.raises(VisibilityViolation, match=reason):
        _build(_block(ref), event)


def test_unfinished_tool_start_cannot_be_projected_as_a_completed_result() -> None:
    block = _block()
    block = block.model_copy(
        update={"type": "tool_result", "tool_call_id": "tool-1"}
    )
    start = _event(available_seq=None, kind="tool_start", call_id="tool-1")
    with pytest.raises(VisibilityViolation, match="unfinished_tool_result"):
        _build(block, start)


def test_derived_evaluator_taint_cannot_be_laundered_by_hash_or_summary() -> None:
    derived = propagate_label(
        [
            InformationLabel(
                scope="evaluator", run_id="run-1", available_seq=1, taints=["test_patch"]
            )
        ]
    )
    derived_ref = _ref().model_copy(update={"labels": [derived]})
    with pytest.raises(VisibilityViolation, match="tainted_evidence"):
        _build(_block(derived_ref))


def _comparison_inputs():
    now = datetime.now(timezone.utc)
    producer = _ref()
    binding_ref = EvidenceRef(
        blob_hash="d" * 64,
        source_id="acr_runtime",
        trajectory_key="run-1",
        locator="/tools/tool-1/body",
        labels=[InformationLabel(scope="runtime", run_id="run-1", available_seq=1)],
    )
    binding = FileBinding(
        repo_relative_path="target.py",
        file_sha256="d" * 64,
        encoding="utf-8",
        read_event_id="event:run-1:1",
        observed_seq=1,
        complete=True,
    )
    block = ContextBlock(
        kind="context_block",
        id="read-block",
        producer_ref=producer,
        provenance_ref=binding_ref,
        request_id="request-1",
        occurrence_id="request-1:block:0",
        origin_event_id="event:run-1:1",
        role="user",
        type="tool_result",
        tool_call_id="tool-1",
        body_pointer="/messages/0/content",
        content_hash="e" * 64,
        complete=True,
        file_binding=binding,
    )
    read_event = Event(
        kind="tool_finish",
        id="event:run-1:1",
        producer_ref=producer,
        run_id="run-1",
        event_seq=1,
        call_id="tool-1",
        payload_ref=_ref(available_seq=None),
        available_seq=1,
        start=now,
        end=now,
    )
    current_ref = EvidenceRef(
        blob_hash="d" * 64,
        source_id="acr_runtime",
        trajectory_key="run-1",
        locator="/state-checks/2/target.py",
        labels=[InformationLabel(scope="runtime", run_id="run-1", available_seq=2)],
    )
    comparison = FileComparison(
        binding_ref=binding_ref,
        current_file_sha256="d" * 64,
        current_file_ref=current_ref,
        checked_seq=2,
        status="same",
    )
    state_check = Event(
        kind="state_check",
        id="event:run-1:2",
        producer_ref=producer,
        run_id="run-1",
        event_seq=2,
        call_id=binding.read_event_id,
        payload_ref=_ref(available_seq=None),
        available_seq=2,
        start=now,
        end=now,
    )
    return producer, block, comparison, [read_event, state_check]


def test_build_view_requires_one_exact_current_request_binding() -> None:
    producer, block, comparison, events = _comparison_inputs()
    view = build_view(
        run_id="run-1",
        cutoff_seq=2,
        request_draft_hash="f" * 64,
        blocks=[block],
        file_comparisons=[comparison],
        events=events,
        producer_ref=producer,
    )
    assert view.file_comparisons == [comparison]


def test_build_view_rejects_unrelated_file_comparison_before_send() -> None:
    producer, block, comparison, events = _comparison_inputs()
    unrelated = comparison.model_copy(
        update={
            "binding_ref": comparison.binding_ref.model_copy(
                update={"locator": "/tools/another-read/body"}
            )
        }
    )
    with pytest.raises(VisibilityViolation, match="file_comparison_binding_mismatch"):
        build_view(
            run_id="run-1",
            cutoff_seq=2,
            request_draft_hash="f" * 64,
            blocks=[block],
            file_comparisons=[unrelated],
            events=events,
            producer_ref=producer,
        )


def test_build_view_rejects_ambiguous_duplicate_occurrence_binding() -> None:
    producer, block, comparison, events = _comparison_inputs()
    duplicate = block.model_copy(
        update={"id": "read-block-copy", "occurrence_id": "request-1:block:1"}
    )
    with pytest.raises(VisibilityViolation, match="file_comparison_binding_mismatch"):
        build_view(
            run_id="run-1",
            cutoff_seq=2,
            request_draft_hash="f" * 64,
            blocks=[block, duplicate],
            file_comparisons=[comparison],
            events=events,
            producer_ref=producer,
        )
