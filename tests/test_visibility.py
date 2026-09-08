"""Frozen anti-cheating checks for the narrow DecisionView boundary."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from acr.contracts import (
    ContextBlock,
    Event,
    EvidenceRef,
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
