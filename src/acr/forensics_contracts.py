"""F0 Agent Forensics evidence contracts.

PROVISIONAL UNTIL F0.5 PASS. These models make the selected hypothesis concrete
enough to test against a synthetic incident. They do not establish Claude Code
interface behavior, checkpoint feasibility, verifier binding, restore fidelity,
or a production incident analyzer.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from acr.contracts import ContractModel, Envelope, EvidenceRef, Fact

FORENSICS_CONTRACT_STATUS = "PROVISIONAL UNTIL F0.5 PASS"
ProvisionalStatus = Literal["provisional_until_f0_5_pass"]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1)]


class ProvisionalForensicsRecord(Envelope):
    """Shared marker for F0 records; not a sixth domain object."""

    contract_status: ProvisionalStatus = "provisional_until_f0_5_pass"


class OrderingEvidence(ContractModel):
    """An ordering claim with its evidence, independent of any hook field."""

    sequence: Fact[int]
    basis: Identifier


class OperationIdentity(ContractModel):
    """Optional tool or operation occurrence without a Claude-specific schema."""

    occurrence_id: Identifier
    name: Identifier


class AgentEvent(ProvisionalForensicsRecord):
    """One provisional agent/tool occurrence backed by optional raw evidence."""

    kind: Literal["agent_event"] = "agent_event"
    session_id: Identifier
    ordering: OrderingEvidence
    timestamp: datetime
    event_kind: Identifier
    operation: OperationIdentity | None = None
    raw_evidence_ref: EvidenceRef | None = None


class CapturedPathState(ContractModel):
    """State of one path inside the explicitly captured repository scope."""

    repo_relative_path: Identifier
    path_kind: Literal["tracked", "selected_untracked"]
    state: Literal["present", "deleted"]
    state_ref: EvidenceRef
    content_ref: EvidenceRef | None = None

    @field_validator("repo_relative_path")
    @classmethod
    def require_repository_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("captured paths must be repository-relative")
        return value

    @model_validator(mode="after")
    def enforce_content_semantics(self) -> CapturedPathState:
        if self.state == "present" and self.content_ref is None:
            raise ValueError("present captured paths require content evidence")
        if self.state == "deleted" and self.content_ref is not None:
            raise ValueError("deleted captured paths cannot claim current content")
        return self


class CaptureScopeEntry(ContractModel):
    """One explicit included, excluded, unsupported, or unknown capture area."""

    area: Literal[
        "tracked_regular_files",
        "selected_untracked_files",
        "ignored_files",
        "environment",
        "running_processes",
        "database",
        "network",
    ]
    repo_relative_path: str | None = None
    captured: Fact[bool]
    disposition: Literal["included", "excluded_by_policy", "not_captured", "unsupported"] | None
    reason: str | None = None

    @field_validator("repo_relative_path")
    @classmethod
    def require_repository_relative_path(cls, value: str | None) -> str | None:
        if value is not None:
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("capture-scope paths must be repository-relative")
        return value

    @model_validator(mode="after")
    def require_gap_reason(self) -> CaptureScopeEntry:
        if self.captured.status == "unknown":
            if self.disposition is not None or not self.reason:
                raise ValueError("unknown capture status requires only an explicit reason")
        elif self.captured.value is True:
            if self.disposition != "included":
                raise ValueError("captured scope entries must be included")
        elif self.disposition not in {"excluded_by_policy", "not_captured", "unsupported"}:
            raise ValueError("uncaptured scope entries require an explicit disposition")
        elif not self.reason:
            raise ValueError("capture gaps require a reason")
        return self


class WorkspaceCheckpoint(ProvisionalForensicsRecord):
    """Manifest of explicitly captured repository scope, never full machine state."""

    kind: Literal["workspace_checkpoint"] = "workspace_checkpoint"
    session_id: Identifier
    ordering: OrderingEvidence
    timestamp: datetime
    git_base: Fact[str]
    captured_workspace_manifest_hash: Sha256
    manifest_ref: EvidenceRef
    captured_paths: list[CapturedPathState]
    capture_scope: list[CaptureScopeEntry] = Field(min_length=1)
    capture_completeness: Fact[bool]
    trigger: Fact[str]
    manifest_scope: Literal["explicitly_captured_repository_scope"] = (
        "explicitly_captured_repository_scope"
    )

    @model_validator(mode="after")
    def enforce_captured_scope_semantics(self) -> WorkspaceCheckpoint:
        paths = [item.repo_relative_path for item in self.captured_paths]
        if len(paths) != len(set(paths)):
            raise ValueError("captured checkpoint paths must be unique")
        has_gap = any(
            item.captured.status == "unknown" or item.captured.value is False
            for item in self.capture_scope
        )
        if has_gap and self.capture_completeness.value is True:
            raise ValueError("capture gaps cannot produce complete captured scope")
        return self


class VerificationReceipt(ProvisionalForensicsRecord):
    """Observed verifier result bound to a captured pre-execution state."""

    kind: Literal["verification_receipt"] = "verification_receipt"
    session_id: Identifier
    verifier_id: Identifier
    verifier_spec_hash: Sha256
    pre_checkpoint_id: Identifier
    tested_captured_workspace_manifest_hash: Sha256
    command: Fact[str]
    passed: Fact[bool]
    exit_code: Fact[int]
    started_at: Fact[datetime]
    finished_at: Fact[datetime]
    stdout_ref: EvidenceRef | None = None
    stderr_ref: EvidenceRef | None = None
    post_checkpoint_id: str | None = None

    @model_validator(mode="after")
    def keep_post_state_separate(self) -> VerificationReceipt:
        if self.post_checkpoint_id == self.pre_checkpoint_id:
            raise ValueError("post checkpoint must be distinct from tested pre-checkpoint")
        return self


class FailureWindow(ContractModel):
    """Explicit report interval without a causal interpretation."""

    start_checkpoint_id: Identifier
    end_checkpoint_id: Identifier
    event_ids: list[Identifier]


class IncidentReport(ProvisionalForensicsRecord):
    """Analyzer-version-dependent derived view, never primary evidence."""

    kind: Literal["incident_report"] = "incident_report"
    evidence_role: Literal["derived_view"] = "derived_view"
    session_id: Identifier
    last_observed_passing_checkpoint_id: Identifier
    first_observed_failing_checkpoint_id: Identifier
    failure_window: FailureWindow
    mutations_inside_window: list[Identifier]
    verification_receipt_ids: list[Identifier] = Field(min_length=1)
    recovery_attempt_event_ids: list[Identifier]
    capture_gaps: list[CaptureScopeEntry]
    unknowns: list[Fact[str]]
    analyzer_version: Identifier

    @model_validator(mode="after")
    def enforce_derived_view_semantics(self) -> IncidentReport:
        if self.provenance_ref is None:
            raise ValueError("derived incident reports require provenance")
        if self.failure_window.start_checkpoint_id != self.last_observed_passing_checkpoint_id:
            raise ValueError("failure window must start at the last observed passing checkpoint")
        if self.failure_window.end_checkpoint_id != self.first_observed_failing_checkpoint_id:
            raise ValueError("failure window must end at the first observed failing checkpoint")
        if any(fact.status != "unknown" for fact in self.unknowns):
            raise ValueError("incident unknowns must use explicit unknown Fact semantics")
        return self


class ForkReceipt(ProvisionalForensicsRecord):
    """Schema-only action receipt limited to captured repository scope."""

    kind: Literal["fork_receipt"] = "fork_receipt"
    session_id: Identifier
    source_checkpoint_id: Identifier
    expected_captured_workspace_manifest_hash: Sha256
    action_status: Literal["not_executed", "succeeded", "failed"]
    target_path: Fact[str]
    restored_captured_scope: Fact[bool]
    recomputed_captured_workspace_manifest_hash: Fact[str]
    manifest_verified: Fact[bool]
    claim_scope: Literal["captured_repository_scope"] = "captured_repository_scope"
    timestamp: datetime

    @model_validator(mode="after")
    def enforce_action_claim_boundary(self) -> ForkReceipt:
        action_facts = (
            self.target_path,
            self.restored_captured_scope,
            self.recomputed_captured_workspace_manifest_hash,
            self.manifest_verified,
        )
        if self.action_status == "not_executed":
            if any(fact.status != "not_applicable" for fact in action_facts):
                raise ValueError("unexecuted forks require not_applicable action facts")
        elif self.action_status == "succeeded":
            if any(fact.status != "observed" for fact in action_facts):
                raise ValueError("successful fork action facts must be observed")
            if self.restored_captured_scope.value is not True or self.manifest_verified.value is not True:
                raise ValueError("successful forks require observed captured-scope verification")
            if (
                self.recomputed_captured_workspace_manifest_hash.value
                != self.expected_captured_workspace_manifest_hash
            ):
                raise ValueError("successful fork manifest must match the captured source scope")
        return self
