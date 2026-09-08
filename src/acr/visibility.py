"""Minimal same-run, completed-prefix DecisionView construction."""

from __future__ import annotations

from acr.contracts import (
    ContextBlock,
    DecisionView,
    Event,
    EvidenceRef,
    FileComparison,
    InformationLabel,
)


class VisibilityViolation(ValueError):
    """A deterministic rejection at the frozen DecisionView boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _authorize_ref(ref: EvidenceRef, run_id: str, cutoff_seq: int) -> None:
    if not ref.labels:
        raise VisibilityViolation("unknown_visibility")
    for label in ref.labels:
        if label.taints:
            raise VisibilityViolation("tainted_evidence")
        if label.scope in {"evaluator", "analysis"}:
            raise VisibilityViolation("unauthorized_scope")
        if label.scope == "public":
            if label.run_id is not None:
                raise VisibilityViolation("cross_run_evidence")
            if label.available_seq is not None and label.available_seq > cutoff_seq:
                raise VisibilityViolation("future_evidence")
            continue
        if label.run_id != run_id:
            raise VisibilityViolation("cross_run_evidence")
        if label.available_seq is None:
            raise VisibilityViolation("unknown_visibility")
        if label.available_seq > cutoff_seq:
            raise VisibilityViolation("future_evidence")


def _completed_event(
    events: list[Event], block: ContextBlock, run_id: str, cutoff_seq: int
) -> Event:
    matches = [event for event in events if event.id == block.origin_event_id]
    if len(matches) != 1:
        raise VisibilityViolation("origin_occurrence_mismatch")
    event = matches[0]
    if event.run_id != run_id:
        raise VisibilityViolation("cross_run_evidence")
    if event.available_seq is None or event.end is None:
        raise VisibilityViolation("unfinished_tool_result")
    if event.available_seq > cutoff_seq:
        raise VisibilityViolation("future_evidence")
    expected_kind = "tool_finish" if block.type == "tool_result" else "response"
    if event.kind != expected_kind or (
        block.type == "tool_result" and event.call_id != block.tool_call_id
    ):
        raise VisibilityViolation("origin_occurrence_mismatch")
    return event


def _public_label() -> list[InformationLabel]:
    return [InformationLabel(scope="public")]


def _event_label(event: Event) -> list[InformationLabel]:
    taints = sorted(
        {
            taint
            for label in event.payload_ref.labels
            for taint in label.taints
        }
    )
    return [
        InformationLabel(
            scope="runtime",
            run_id=event.run_id,
            available_seq=event.available_seq,
            taints=taints,
        )
    ]


def build_view(
    *,
    run_id: str,
    cutoff_seq: int,
    request_draft_hash: str,
    blocks: list[ContextBlock],
    file_comparisons: list[FileComparison],
    events: list[Event],
    producer_ref: EvidenceRef,
    policy_version: str = "decision_view_v1",
    view_id: str | None = None,
) -> DecisionView:
    """Project only authorized public constants and completed same-run prefix evidence."""

    for block in blocks:
        if block.producer_ref != producer_ref:
            raise VisibilityViolation("cross_run_evidence")
        if not block.complete or block.provenance_ref is None:
            raise VisibilityViolation("unknown_visibility")
        _authorize_ref(block.provenance_ref, run_id, cutoff_seq)
        if block.type in {"system_prompt", "task_instruction"}:
            if block.provenance_ref.labels != _public_label():
                raise VisibilityViolation("provenance_label_mismatch")
        elif block.type in {"assistant_response", "tool_result"}:
            origin = _completed_event(events, block, run_id, cutoff_seq)
            if block.provenance_ref.labels != _event_label(origin):
                raise VisibilityViolation("provenance_label_mismatch")
        else:
            raise VisibilityViolation("unknown_visibility")
    for comparison in file_comparisons:
        if comparison.checked_seq > cutoff_seq:
            raise VisibilityViolation("future_evidence")
        _authorize_ref(comparison.binding_ref, run_id, cutoff_seq)
        if comparison.current_file_ref is not None:
            _authorize_ref(comparison.current_file_ref, run_id, cutoff_seq)
        matching_blocks = [
            block
            for block in blocks
            if block.file_binding is not None
            and block.provenance_ref == comparison.binding_ref
        ]
        if len(matching_blocks) != 1:
            raise VisibilityViolation("file_comparison_binding_mismatch")
        block = matching_blocks[0]
        binding = block.file_binding
        assert binding is not None
        if (
            binding.file_sha256 != comparison.binding_ref.blob_hash
            or binding.read_event_id != block.origin_event_id
            or comparison.binding_ref.trajectory_key != run_id
        ):
            raise VisibilityViolation("file_comparison_binding_mismatch")
        state_checks = [
            event
            for event in events
            if event.kind == "state_check"
            and event.run_id == run_id
            and event.available_seq == comparison.checked_seq
            and event.call_id == binding.read_event_id
        ]
        if len(state_checks) != 1:
            raise VisibilityViolation("file_comparison_state_check_mismatch")
        if comparison.current_file_ref is not None and (
            comparison.current_file_ref.labels != _event_label(state_checks[0])
        ):
            raise VisibilityViolation("provenance_label_mismatch")
    identifier = view_id or f"decision-view:{run_id}:{cutoff_seq}:{request_draft_hash[:12]}"
    return DecisionView(
        kind="decision_view",
        id=identifier,
        producer_ref=producer_ref,
        run_id=run_id,
        cutoff_seq=cutoff_seq,
        request_draft_hash=request_draft_hash,
        blocks=blocks,
        file_comparisons=file_comparisons,
        policy_version=policy_version,
        labels=[InformationLabel(scope="runtime", run_id=run_id, available_seq=cutoff_seq)],
    )
