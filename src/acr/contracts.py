"""Versioned, serializable evidence contracts for the ACR MVP.

These models intentionally describe evidence and experiment records only.  They
do not perform runtime, provider, policy, or evaluator work.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"

Scope = Literal["public", "runtime", "evaluator", "analysis"]
FactStatus = Literal["observed", "derived", "estimated", "unknown", "not_applicable"]

T = TypeVar("T")


class ContractModel(BaseModel):
    """Shared strict JSON-model behavior for all MVP contracts."""

    model_config = ConfigDict(extra="forbid")


class InformationLabel(ContractModel):
    """Visibility and taint metadata retained with an object or reference."""

    scope: Scope
    run_id: str | None = None
    available_seq: int | None = Field(default=None, ge=0)
    taints: list[str] = Field(default_factory=list)


class EvidenceRef(ContractModel):
    """A reference to one source occurrence, not merely to its content bytes."""

    blob_hash: str
    source_id: str
    trajectory_key: str
    locator: str
    labels: list[InformationLabel] = Field(default_factory=list)

    @property
    def occurrence_identity(self) -> tuple[str, str, str]:
        """Stable source-location identity; intentionally excludes ``blob_hash``."""

        return (self.source_id, self.trajectory_key, self.locator)


class Fact(ContractModel, Generic[T]):
    """A value together with its epistemic status and evidence references."""

    value: T | None = None
    status: FactStatus
    reason: str | None = None
    refs: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_status_semantics(self) -> Fact[T]:
        if self.status == "unknown":
            if self.value is not None:
                raise ValueError("unknown facts must have a null value")
            if not self.reason or not self.reason.strip():
                raise ValueError("unknown facts require a reason")
        elif self.status == "not_applicable":
            if self.value is not None:
                raise ValueError("not_applicable facts must have a null value")
        else:
            if self.value is None:
                raise ValueError(f"{self.status} facts require a value")
            if self.status in {"observed", "derived"} and not self.refs:
                raise ValueError(f"{self.status} facts require evidence references")
        return self


class Envelope(ContractModel):
    """Required envelope for every persistent top-level object."""

    kind: str
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    id: str
    producer_ref: EvidenceRef
    provenance_ref: EvidenceRef | None = None


class FileBinding(ContractModel):
    repo_relative_path: str
    file_sha256: str
    range: Literal["full"] = "full"
    encoding: str
    read_event_id: str
    observed_seq: int = Field(ge=0)
    complete: bool


class ContextBlock(Envelope):
    request_id: str
    occurrence_id: str
    origin_event_id: str
    role: str
    type: str
    tool_call_id: str | None = None
    body_pointer: str
    content_hash: str
    complete: bool
    file_binding: FileBinding | None = None


class Event(Envelope):
    run_id: str
    event_seq: int = Field(ge=0)
    source_position: str | int | None = None
    kind: Literal[
        "request",
        "response",
        "tool_start",
        "tool_finish",
        "state_check",
        "decision",
        "manager_span",
        "run_stop",
    ]
    call_id: str | None = None
    payload_ref: EvidenceRef
    available_seq: int | None = Field(default=None, ge=0)
    start: datetime | None = None
    end: datetime | None = None


class RequestSnapshot(Envelope):
    run_id: str
    logical_call_id: str
    attempt_id: str
    cutoff_seq: int = Field(ge=0)
    before_body_ref: EvidenceRef
    sent_body_ref: EvidenceRef | None = None
    ordered_blocks: list[ContextBlock]
    model_config_ref: EvidenceRef
    transport_status: str
    provider_request_id: str | None = None


class RepositoryState(Envelope):
    run_id: str
    initial_tree_hash: str
    image_digest: str
    observed_seq: int = Field(ge=0)
    files: list[FileBinding]
    state_caps: dict[str, str]


class FileComparison(ContractModel):
    binding_ref: EvidenceRef
    current_file_sha256: str | None = None
    checked_seq: int = Field(ge=0)
    status: Literal["same", "changed", "unknown"]
    reason: str | None = None

    @model_validator(mode="after")
    def require_reason_for_unknown(self) -> FileComparison:
        if self.status == "unknown" and not self.reason:
            raise ValueError("unknown file comparisons require a reason")
        return self


class DecisionView(Envelope):
    run_id: str
    cutoff_seq: int = Field(ge=0)
    request_draft_hash: str
    blocks: list[ContextBlock]
    file_comparisons: list[FileComparison]
    policy_version: str
    labels: list[InformationLabel]


class Candidate(Envelope):
    run_id: str
    view_id: str
    rule_version: str
    older_occurrence: str
    newest_occurrence: str
    evidence_refs: list[EvidenceRef] = Field(min_length=1)
    confidence_tier: Literal["rule_high"] = "rule_high"
    preconditions: list[str]


class InterventionPlan(Envelope):
    op: Literal["omit_one_duplicate_read_v1"] = "omit_one_duplicate_read_v1"
    candidate_id: str
    expected_request_hash: str
    target_pointer: str
    replacement_text: str
    expected_file_hash: str


class InterventionReceipt(Envelope):
    plan_id: str
    status: Literal["rejected", "prepared", "sent", "accepted", "send_unknown"]
    reason: str | None = None
    before_hash: str
    prepared_after_hash: str | None = None
    sent_request_id: str | None = None
    actual_sent_hash: str | None = None
    changed_pointers: list[str]
    started: datetime | None = None
    ended: datetime | None = None


class Run(Envelope):
    task_id: str
    config_ref: EvidenceRef
    capabilities: dict[str, str]
    initial_state_ref: EvidenceRef
    start: datetime | None = None
    end: datetime | None = None
    status: str
    stop_reason: str | None = None
    events_ref: EvidenceRef
    sealed_artifact_ref: EvidenceRef | None = None
    sealed_artifact_hash: str | None = None


class Pair(Envelope):
    task_id: str
    replicate_id: str
    baseline_run_id: str
    treatment_run_id: str
    manifest_hash: str
    execution_order: Literal["AB", "BA"]
    preflight_result: Fact[bool]
    status: str
    mode: Literal["from_scratch"] = "from_scratch"


class EvaluationResult(Envelope):
    run_id: str
    submitted_artifact_hash: str
    evaluator_revision: str
    status: Literal["completed", "infra_error"]
    patch_valid: Fact[bool]
    tests_executed: Fact[int]
    passed: Fact[int]
    failed: Fact[int]
    resolved: Fact[bool]
    raw_result_ref: EvidenceRef


class CostEntry(Envelope):
    run_id: str
    attempt_id: str | None = None
    resource_id: str | None = None
    caller: Literal["agent", "manager", "tool", "environment", "evaluator", "instrumentation"]
    phase: Literal["run", "evaluation", "research"]
    category: str
    quantity: Fact[float]
    unit: str
    rate_ref: EvidenceRef | None = None
    amount: Fact[float]
    currency: str | None = None
    evidence_level: str
    raw_usage_ref: EvidenceRef | None = None
    dedup_key: str

    @model_validator(mode="after")
    def require_charge_identity(self) -> CostEntry:
        if self.attempt_id is None and self.resource_id is None:
            raise ValueError("cost entries require an attempt_id or resource_id")
        return self


class Provenance(Envelope):
    output_object: str
    field: str
    input_refs: list[EvidenceRef] = Field(min_length=1)
    transform_name: str
    transform_version: str
    config_ref: EvidenceRef | None = None


class AuditFinding(Envelope):
    rule_id: str
    rule_version: str
    severity: Literal["block", "warn", "info"]
    scope: Scope
    object_ref: EvidenceRef
    evidence_refs: list[EvidenceRef]
    action: str
    message: str


_SCOPE_RESTRICTION = {"public": 0, "runtime": 1, "analysis": 2, "evaluator": 3}


def propagate_label(labels: list[InformationLabel]) -> InformationLabel:
    """Derive conservative label metadata without silently dropping taints.

    Same-run inputs retain their run ID. Public constants may have ``run_id``
    omitted. Mixing distinct non-null run IDs is rejected rather than guessed.
    If any source sequence is unknown, the derived sequence stays unknown.
    """

    if not labels:
        raise ValueError("derived labels require at least one input label")

    run_ids = {label.run_id for label in labels if label.run_id is not None}
    if len(run_ids) > 1:
        raise ValueError("cannot derive a label from multiple runs")

    taints = sorted({taint for label in labels for taint in label.taints})
    scope = max(labels, key=lambda label: _SCOPE_RESTRICTION[label.scope]).scope
    available_seq = (
        None
        if any(label.available_seq is None for label in labels)
        else max(label.available_seq for label in labels if label.available_seq is not None)
    )
    return InformationLabel(
        scope=scope,
        run_id=next(iter(run_ids), None),
        available_seq=available_seq,
        taints=taints,
    )
