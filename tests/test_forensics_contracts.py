"""F0 tests for provisional Agent Forensics contracts and synthetic evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from acr.forensics_contracts import (
    FORENSICS_CONTRACT_STATUS,
    AgentEvent,
    CapturedPathState,
    ForkReceipt,
    IncidentReport,
    VerificationReceipt,
    WorkspaceCheckpoint,
    canonical_captured_state_manifest_bytes,
    captured_state_manifest_hash,
)

FIXTURE = Path("tests/fixtures/forensics/f0_synthetic_incident.json")


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def parse_records(data: dict[str, Any]) -> tuple[
    list[AgentEvent],
    list[WorkspaceCheckpoint],
    list[VerificationReceipt],
    IncidentReport,
    ForkReceipt,
]:
    records = data["records"]
    return (
        [AgentEvent.model_validate(item) for item in records["agent_events"]],
        [
            WorkspaceCheckpoint.model_validate(item)
            for item in records["workspace_checkpoints"]
        ],
        [
            VerificationReceipt.model_validate(item)
            for item in records["verification_receipts"]
        ],
        IncidentReport.model_validate(records["incident_report"]),
        ForkReceipt.model_validate(records["fork_receipt"]),
    )


def evidence_refs(value: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if {"blob_hash", "source_id", "trajectory_key", "locator"} <= value.keys():
            refs.append(value)
        for nested in value.values():
            refs.extend(evidence_refs(nested))
    elif isinstance(value, list):
        for nested in value:
            refs.extend(evidence_refs(nested))
    return refs


def resolve_json_pointer(raw: str, pointer: str) -> Any:
    if not pointer:
        return raw
    value: Any = json.loads(raw)
    for part in pointer.removeprefix("/").split("/"):
        token = part.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def test_all_f0_contracts_round_trip_with_provisional_status() -> None:
    data = load_fixture()
    events, checkpoints, receipts, report, fork_receipt = parse_records(data)

    records = [*events, *checkpoints, *receipts, report, fork_receipt]
    assert data["contract_status"] == FORENSICS_CONTRACT_STATUS
    assert {type(record) for record in records} == {
        AgentEvent,
        WorkspaceCheckpoint,
        VerificationReceipt,
        IncidentReport,
        ForkReceipt,
    }
    for record in records:
        assert record.contract_status == "provisional_pending_separate_freeze"
        assert type(record).model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("ordinary_value", [False, 0, "", "unknown"])
def test_incident_unknown_cannot_be_replaced_by_ordinary_values(
    ordinary_value: object,
) -> None:
    data = load_fixture()["records"]["incident_report"]
    mutated = copy.deepcopy(data)
    mutated["unknowns"][0]["value"] = ordinary_value

    with pytest.raises(ValidationError):
        IncidentReport.model_validate(mutated)

    report = IncidentReport.model_validate(data)
    assert report.unknowns[0].status == "unknown"
    assert report.unknowns[0].value is None
    assert report.unknowns[0].reason == "external_process_state_not_captured"


def test_captured_manifest_is_limited_to_explicit_repository_scope() -> None:
    data = load_fixture()["records"]["workspace_checkpoints"]
    checkpoints = [WorkspaceCheckpoint.model_validate(item) for item in data]

    assert all(
        checkpoint.manifest_scope == "explicitly_captured_repository_scope"
        for checkpoint in checkpoints
    )
    assert all(
        checkpoint.manifest_ref.blob_hash == checkpoint.captured_workspace_manifest_hash
        for checkpoint in checkpoints
    )
    assert all(checkpoint.capture_completeness.value is False for checkpoint in checkpoints)
    assert all(
        any(
            entry.repo_relative_path == ".env"
            and entry.captured.value is False
            and entry.disposition == "excluded_by_policy"
            and entry.reason == "excluded_by_policy"
            for entry in checkpoint.capture_scope
        )
        for checkpoint in checkpoints
    )

    for forbidden_scope in ("complete_workspace", "machine_state", "full_repository"):
        mutated = copy.deepcopy(data[0])
        mutated["manifest_scope"] = forbidden_scope
        with pytest.raises(ValidationError):
            WorkspaceCheckpoint.model_validate(mutated)

    falsely_complete = copy.deepcopy(data[0])
    falsely_complete["capture_completeness"]["value"] = True
    with pytest.raises(ValidationError, match="capture gaps cannot produce complete"):
        WorkspaceCheckpoint.model_validate(falsely_complete)

    explicitly_unknown = copy.deepcopy(data[0])
    explicitly_unknown["capture_scope"][1]["captured"] = {
        "value": None,
        "status": "unknown",
        "reason": "capture_outcome_not_observed",
        "refs": [],
    }
    explicitly_unknown["capture_scope"][1]["disposition"] = None
    explicitly_unknown["capture_scope"][1]["reason"] = "capture_outcome_not_observed"
    unknown_checkpoint = WorkspaceCheckpoint.model_validate(explicitly_unknown)
    assert unknown_checkpoint.capture_scope[1].captured.status == "unknown"


def test_manifest_reference_hash_mismatch_is_rejected() -> None:
    data = copy.deepcopy(load_fixture()["records"]["workspace_checkpoints"][0])
    data["manifest_ref"]["blob_hash"] = "0" * 64

    with pytest.raises(ValidationError, match="manifest reference must match canonical"):
        WorkspaceCheckpoint.model_validate(data)


def test_matching_forged_manifest_hashes_are_rejected() -> None:
    data = copy.deepcopy(load_fixture()["records"]["workspace_checkpoints"][0])
    wrong_hash = "0" * 64
    assert wrong_hash != data["captured_workspace_manifest_hash"]
    data["captured_workspace_manifest_hash"] = wrong_hash
    data["manifest_ref"]["blob_hash"] = wrong_hash

    with pytest.raises(ValidationError, match="must match canonical captured-state hash"):
        WorkspaceCheckpoint.model_validate(data)


def test_captured_state_change_without_manifest_hash_update_is_rejected() -> None:
    data = copy.deepcopy(load_fixture()["records"]["workspace_checkpoints"][0])
    replacement_content_hash = "1" * 64
    assert replacement_content_hash != data["captured_paths"][0]["content_ref"]["blob_hash"]
    data["captured_paths"][0]["content_ref"]["blob_hash"] = replacement_content_hash

    with pytest.raises(ValidationError, match="must match canonical captured-state hash"):
        WorkspaceCheckpoint.model_validate(data)


def test_identical_captured_state_has_same_identity_across_checkpoint_occurrences() -> None:
    checkpoint_data = load_fixture()["records"]["workspace_checkpoints"][0]
    checkpoint_a = WorkspaceCheckpoint.model_validate(checkpoint_data)
    different_occurrence = copy.deepcopy(checkpoint_data)
    different_occurrence["id"] = "cp-same-state-later"
    different_occurrence["timestamp"] = "2026-01-01T00:01:00Z"
    different_occurrence["trigger"] = {
        "value": None,
        "status": "unknown",
        "reason": "different_occurrence_trigger_not_observed",
        "refs": [],
    }
    checkpoint_b = WorkspaceCheckpoint.model_validate(different_occurrence)

    assert checkpoint_a.id != checkpoint_b.id
    assert checkpoint_a.timestamp != checkpoint_b.timestamp
    assert checkpoint_a.trigger.value != checkpoint_b.trigger.value
    assert checkpoint_a.captured_workspace_manifest_hash == (
        checkpoint_b.captured_workspace_manifest_hash
    )
    assert canonical_captured_state_manifest_bytes(
        checkpoint_a.git_base.value,
        checkpoint_a.captured_paths,
    ) == canonical_captured_state_manifest_bytes(
        checkpoint_b.git_base.value,
        checkpoint_b.captured_paths,
    )


def test_git_base_participates_in_captured_state_identity() -> None:
    checkpoint = WorkspaceCheckpoint.model_validate(
        load_fixture()["records"]["workspace_checkpoints"][0]
    )
    original_hash = captured_state_manifest_hash(
        checkpoint.git_base.value,
        checkpoint.captured_paths,
    )
    different_base_hash = captured_state_manifest_hash(
        "different-synthetic-git-base",
        checkpoint.captured_paths,
    )

    assert original_hash == checkpoint.captured_workspace_manifest_hash
    assert different_base_hash != original_hash


def test_executable_state_participates_in_captured_state_identity() -> None:
    checkpoint = WorkspaceCheckpoint.model_validate(
        load_fixture()["records"]["workspace_checkpoints"][0]
    )
    non_executable = checkpoint.captured_paths[0]
    executable = non_executable.model_copy(update={"executable": True})

    assert non_executable.content_ref == executable.content_ref
    assert captured_state_manifest_hash(
        checkpoint.git_base.value,
        [non_executable],
    ) != captured_state_manifest_hash(
        checkpoint.git_base.value,
        [executable],
    )


def test_present_and_deleted_paths_enforce_executable_semantics() -> None:
    path = load_fixture()["records"]["workspace_checkpoints"][0]["captured_paths"][0]

    present_without_executable = copy.deepcopy(path)
    present_without_executable["executable"] = None
    with pytest.raises(ValidationError, match="require executable state"):
        CapturedPathState.model_validate(present_without_executable)

    deleted_with_executable = copy.deepcopy(path)
    deleted_with_executable["state"] = "deleted"
    deleted_with_executable["content_ref"] = None
    deleted_with_executable["executable"] = False
    with pytest.raises(ValidationError, match="cannot claim executable state"):
        CapturedPathState.model_validate(deleted_with_executable)


def test_canonical_manifest_path_order_does_not_change_identity() -> None:
    checkpoint = WorkspaceCheckpoint.model_validate(
        load_fixture()["records"]["workspace_checkpoints"][0]
    )
    second_path = CapturedPathState.model_validate(
        {
            **checkpoint.captured_paths[0].model_dump(mode="json"),
            "repo_relative_path": "README.md",
        }
    )
    first_order = [checkpoint.captured_paths[0], second_path]
    reverse_order = list(reversed(first_order))

    assert canonical_captured_state_manifest_bytes(
        checkpoint.git_base.value,
        first_order,
    ) == canonical_captured_state_manifest_bytes(
        checkpoint.git_base.value,
        reverse_order,
    )
    assert captured_state_manifest_hash(
        checkpoint.git_base.value,
        first_order,
    ) == captured_state_manifest_hash(
        checkpoint.git_base.value,
        reverse_order,
    )


def test_verification_receipts_bind_the_captured_pre_state() -> None:
    _, checkpoints, receipts, _, _ = parse_records(load_fixture())
    checkpoints_by_id = {checkpoint.id: checkpoint for checkpoint in checkpoints}

    for receipt in receipts:
        pre_checkpoint = checkpoints_by_id[receipt.pre_checkpoint_id]
        assert (
            receipt.tested_captured_workspace_manifest_hash
            == pre_checkpoint.captured_workspace_manifest_hash
        )
        assert receipt.post_checkpoint_id is None

    assert receipts[0].passed.value is True
    assert receipts[0].pre_checkpoint_id == "cp-01"
    assert receipts[1].passed.value is False
    assert receipts[1].pre_checkpoint_id == "cp-03"
    assert receipts[2].passed.value is False
    assert receipts[2].pre_checkpoint_id == "cp-03"

    invalid = copy.deepcopy(load_fixture()["records"]["verification_receipts"][0])
    invalid["post_checkpoint_id"] = invalid["pre_checkpoint_id"]
    with pytest.raises(ValidationError, match="distinct from tested pre-checkpoint"):
        VerificationReceipt.model_validate(invalid)


def test_incident_report_is_a_non_causal_derived_view() -> None:
    data = load_fixture()["records"]["incident_report"]
    report = IncidentReport.model_validate(data)

    assert report.evidence_role == "derived_view"
    assert report.provenance_ref is not None
    assert report.last_observed_passing_checkpoint_id == "cp-01"
    assert report.first_observed_failing_checkpoint_id == "cp-03"
    assert report.failure_window.start_checkpoint_id == "cp-01"
    assert report.failure_window.end_checkpoint_id == "cp-03"
    assert report.mutations_inside_window == ["event-02-edit", "event-03-bash-mutation"]
    assert report.recovery_attempt_event_ids == [
        "event-04-recovery-read",
        "event-05-recovery-grep",
    ]

    for forbidden_field in ("root_cause", "caused_by", "causal_probability"):
        mutated = copy.deepcopy(data)
        mutated[forbidden_field] = "unsupported synthetic claim"
        with pytest.raises(ValidationError):
            IncidentReport.model_validate(mutated)

    primary_claim = copy.deepcopy(data)
    primary_claim["evidence_role"] = "primary_evidence"
    with pytest.raises(ValidationError):
        IncidentReport.model_validate(primary_claim)


def test_incident_report_capture_gaps_accepts_only_real_gaps() -> None:
    fixture = load_fixture()["records"]
    report = IncidentReport.model_validate(fixture["incident_report"])
    assert all(
        entry.captured.status == "unknown" or entry.captured.value is False
        for entry in report.capture_gaps
    )

    unknown_gap = copy.deepcopy(fixture["incident_report"])
    unknown_gap["capture_gaps"][0]["captured"] = {
        "value": None,
        "status": "unknown",
        "reason": "capture_outcome_not_observed",
        "refs": [],
    }
    unknown_gap["capture_gaps"][0]["disposition"] = None
    unknown_gap["capture_gaps"][0]["reason"] = "capture_outcome_not_observed"
    assert IncidentReport.model_validate(unknown_gap).capture_gaps[0].captured.status == (
        "unknown"
    )

    successful_capture = copy.deepcopy(fixture["workspace_checkpoints"][0]["capture_scope"][0])
    invalid = copy.deepcopy(fixture["incident_report"])
    invalid["capture_gaps"] = [successful_capture]
    with pytest.raises(ValidationError, match="capture_gaps must contain only"):
        IncidentReport.model_validate(invalid)


def test_synthetic_fixture_has_content_addressed_references_and_distinct_occurrences() -> None:
    data = load_fixture()
    raw_evidence = data["raw_evidence"]

    for digest, content in raw_evidence.items():
        assert hashlib.sha256(content.encode()).hexdigest() == digest
    for ref in evidence_refs(data["records"]):
        assert ref["blob_hash"] in raw_evidence
        resolve_json_pointer(raw_evidence[ref["blob_hash"]], ref["locator"])

    events, _, _, _, _ = parse_records(data)
    raw_refs = [event.raw_evidence_ref for event in events]
    assert all(ref is not None for ref in raw_refs)
    assert len({ref.blob_hash for ref in raw_refs if ref is not None}) == 1
    assert len({ref.occurrence_identity for ref in raw_refs if ref is not None}) == len(events)

    _, checkpoints, _, _, _ = parse_records(data)
    for checkpoint in checkpoints:
        canonical_bytes = canonical_captured_state_manifest_bytes(
            checkpoint.git_base.value,
            checkpoint.captured_paths,
        )
        assert raw_evidence[checkpoint.captured_workspace_manifest_hash].encode() == (
            canonical_bytes
        )


def test_synthetic_incident_references_one_complete_expected_story() -> None:
    events, checkpoints, receipts, report, _ = parse_records(load_fixture())
    event_ids = {event.id for event in events}
    checkpoint_ids = {checkpoint.id for checkpoint in checkpoints}
    receipt_ids = {receipt.id for receipt in receipts}

    assert set(report.failure_window.event_ids) <= event_ids
    assert set(report.mutations_inside_window) <= event_ids
    assert set(report.recovery_attempt_event_ids) <= event_ids
    assert set(report.verification_receipt_ids) == receipt_ids
    assert report.last_observed_passing_checkpoint_id in checkpoint_ids
    assert report.first_observed_failing_checkpoint_id in checkpoint_ids
    assert [event.ordering.sequence.value for event in events] == [1, 2, 4, 6, 7]
    assert [receipt.passed.value for receipt in receipts] == [True, False, False]


def test_fork_receipt_is_schema_only_and_captured_scope_limited() -> None:
    data = load_fixture()["records"]["fork_receipt"]
    receipt = ForkReceipt.model_validate(data)

    assert receipt.action_status == "not_executed"
    assert receipt.claim_scope == "captured_repository_scope"
    assert receipt.restored_captured_scope.status == "not_applicable"
    assert receipt.manifest_verified.status == "not_applicable"

    mutated = copy.deepcopy(data)
    mutated["claim_scope"] = "complete_workspace"
    with pytest.raises(ValidationError):
        ForkReceipt.model_validate(mutated)
