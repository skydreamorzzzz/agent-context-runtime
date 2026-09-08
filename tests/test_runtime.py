"""M2 persisted trusted-capture tests using an explicitly engineering-only transport."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from acr.adapters.provider import (
    CapturedProvider,
    DeepSeekHTTPTransport,
    RequestDraft,
    TransportResult,
    serialize_deepseek_chat_request,
)
from acr.audit import audit_evaluation, audit_run
from acr.cli import _within_attempt_budget
from acr.contracts import Run
from acr.evaluation import EvaluationHandoffRejected, LocalAddEvaluator, require_sealed_run
from acr.runtime.runner import CapturedRuntime, RunSealedError, RuntimeTask, run_deepseek_add_smoke
from acr.state import WorkspaceViolation, initial_tree_manifest
from acr.store import ingest_evaluator_bytes, ingest_runtime_bytes, load_blob


def _runtime(tmp_path: Path, *, with_usage: bool = True) -> tuple[CapturedRuntime, list[bytes]]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "a.py").write_text("print('one')\n")
    sent: list[bytes] = []

    def transport(body: bytes, attempt_id: str) -> TransportResult:
        sent.append(body)
        response = {"id": attempt_id}
        if with_usage:
            response["usage"] = {"input_tokens": 3, "output_tokens": 2}
        return TransportResult("ok", json.dumps(response).encode(), f"provider-{attempt_id}")

    runtime = CapturedRuntime(
        data_root=tmp_path / "data",
        run_id="run-1",
        task=RuntimeTask("public/task-1", "Read the public file."),
        workspace=workspace,
        config_bytes=b'{"provider":"engineering-fixture"}',
    )
    return runtime, sent


def _complete(runtime: CapturedRuntime, *, retry: bool = False, with_usage: bool = True):
    reads = []
    sent: list[bytes] = []

    def transport(body: bytes, attempt_id: str) -> TransportResult:
        sent.append(body)
        result = {"id": attempt_id}
        if with_usage:
            result["usage"] = {"input_tokens": 3}
        return TransportResult("ok", json.dumps(result).encode())

    provider = CapturedProvider(transport, send_serializer=lambda prepared: prepared.prepared_body + b"\n")
    reads.append(runtime.tools.read_file("a.py"))
    first = runtime.send_request(provider, b'{"prompt":"draft"}', "call-1")
    if retry:
        runtime.send_request(provider, b'{"prompt":"retry"}', "call-1")
    run = runtime.seal(status="completed")
    return run, first, reads, sent


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


class _HTTPResponse:
    def __init__(self, body: bytes, *, status: int = 200) -> None:
        self._body = body
        self.status = status
        self.headers = {"x-request-id": "header-request-id"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _replace_event_payload(root: Path, events: list[dict], event: dict, payload: dict) -> None:
    ref = ingest_runtime_bytes(
        json.dumps(payload, sort_keys=True).encode(),
        root,
        "run-1",
        f"/events/{event['event_seq']}/payload",
    )
    event["payload_ref"] = ref.model_dump()
    _write_jsonl(root / "runs" / "run-1" / "events.jsonl", events)


def _response_payload(root: Path, events: list[dict]) -> tuple[dict, dict]:
    event = next(event for event in events if event["kind"] == "response")
    return event, json.loads(load_blob(root, event["payload_ref"]["blob_hash"]))


def test_engineering_capture_records_actual_send_boundary_and_persisted_run(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    run, snapshot, reads, sent = _complete(runtime)
    assert sent == [b'{"prompt":"draft"}\n']
    assert load_blob(tmp_path / "data", snapshot.prepared_body_ref.blob_hash) == b'{"prompt":"draft"}'
    assert load_blob(tmp_path / "data", snapshot.sent_body_ref.blob_hash) == sent[0]
    assert snapshot.prepared_body_ref.blob_hash != snapshot.sent_body_ref.blob_hash
    assert reads[0].binding.read_event_id.startswith("event:run-1:")
    assert run.capabilities["runtime_level"] == "engineering_fixture_only"
    assert audit_run(tmp_path / "data", "run-1").status == "PASS"


def test_retry_is_two_physical_attempts_and_failed_attempt_is_retained(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    _complete(runtime, retry=True)
    requests = _jsonl(tmp_path / "data" / "runs" / "run-1" / "requests.jsonl")
    assert [record["attempt_id"] for record in requests] == ["attempt:run-1:0", "attempt:run-1:1"]
    assert audit_run(tmp_path / "data", "run-1").status == "PASS"

    root = tmp_path / "failed"
    runtime, _ = _runtime(root)

    def failed_transport(body: bytes, attempt_id: str) -> TransportResult:
        return TransportResult("failed", b'{"error":"network"}')

    provider = CapturedProvider(failed_transport)
    runtime.send_request(provider, b"draft", "call-1")
    runtime.seal(status="task_failed", stop_reason="provider_failure")
    failed_root = root / "data"
    assert audit_run(failed_root, "run-1").status == "PASS"
    failed_events = _jsonl(failed_root / "runs" / "run-1" / "events.jsonl")
    failed_events[:] = [event for event in failed_events if event["kind"] != "response"]
    (failed_root / "runs" / "run-1" / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in failed_events)
    )
    assert "attempt_occurrence_missing" in audit_run(failed_root, "run-1").blocks


def test_missing_usage_is_unknown_not_zero(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    _complete(runtime, with_usage=False)
    events = _jsonl(tmp_path / "data" / "runs" / "run-1" / "events.jsonl")
    response = next(event for event in events if event["kind"] == "response")
    payload_ref = response["payload_ref"]
    payload = json.loads(load_blob(tmp_path / "data", payload_ref["blob_hash"]))
    assert payload["usage"] == {"value": None, "status": "unknown", "reason": "provider_did_not_report_usage", "refs": []}
    assert audit_run(tmp_path / "data", "run-1").status == "PASS"


def test_file_reads_preserve_occurrence_and_state_change(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    first = runtime.tools.read_file("a.py")
    (runtime.workspace / "a.py").write_text("print('two')\n")
    second = runtime.tools.read_file("a.py")
    assert first.tool_call_id != second.tool_call_id
    assert first.binding.file_sha256 != second.binding.file_sha256
    runtime.seal(status="completed")
    assert audit_run(tmp_path / "data", "run-1").status == "PASS"

    root = tmp_path / "same"
    runtime, _ = _runtime(root)
    first = runtime.tools.read_file("a.py")
    second = runtime.tools.read_file("a.py")
    assert first.body_ref.blob_hash == second.body_ref.blob_hash
    assert first.body_ref.occurrence_identity != second.body_ref.occurrence_identity


def test_workspace_escape_and_private_evaluator_overlap_are_rejected(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    with pytest.raises(WorkspaceViolation):
        runtime.tools.read_file("../outside")
    outside = tmp_path / "outside"
    outside.write_text("private")
    (runtime.workspace / "link").symlink_to(outside)
    with pytest.raises(WorkspaceViolation):
        runtime.tools.read_file("link")
    with pytest.raises(WorkspaceViolation):
        CapturedRuntime(
            data_root=tmp_path / "other-data",
            run_id="bad-run",
            task=RuntimeTask("public/task", "public"),
            workspace=runtime.workspace,
            config_bytes=b"{}",
            private_eval_root=runtime.workspace / "private-eval",
        )


def test_evaluator_boundary_rejects_unsealed_runs_without_loading_private_inputs(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    provisional = runtime.initial_state
    with pytest.raises(EvaluationHandoffRejected):
        # This Run-shaped record has no sealed artifact; no private spec exists here.
        require_sealed_run(
            Run(
                kind="run",
                id="unsealed",
                producer_ref=provisional.producer_ref,
                task_id="public/task",
                config_ref=provisional.producer_ref,
                capabilities={},
                initial_state_ref=provisional.producer_ref,
                status="running",
                events_ref=provisional.producer_ref,
            )
        )
    runtime.seal(status="completed")
    persisted = Run.model_validate_json((tmp_path / "data" / "runs" / "run-1" / "run.json").read_text())
    require_sealed_run(persisted)


def test_seal_blocks_later_events_and_runtime_audit_blocks_mutations(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    _complete(runtime)
    with pytest.raises(RunSealedError):
        runtime.record_event("manager_span", None, {}, True)

    root = tmp_path / "data"
    events_path = root / "runs" / "run-1" / "events.jsonl"
    events = _jsonl(events_path)
    events[:] = [event for event in events if event["kind"] != "tool_finish"]
    events_path.write_text("".join(json.dumps(event) + "\n" for event in events))
    blocks = audit_run(root, "run-1").blocks
    assert "incomplete_tool_call" in blocks


def test_runtime_audit_blocks_wrong_run_ref_file_tamper_and_malformed_evidence(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    _complete(runtime)
    root = tmp_path / "data"
    events_path = root / "runs" / "run-1" / "events.jsonl"
    events = _jsonl(events_path)
    events[0]["payload_ref"]["trajectory_key"] = "other-run"
    events_path.write_text("".join(json.dumps(event) + "\n" for event in events))
    assert "wrong_run_evidence_reference" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "bytes")
    _, _, reads, _ = _complete(runtime)
    blob = (tmp_path / "bytes" / "data" / "blobs" / reads[0].body_ref.blob_hash)
    blob.write_bytes(b"replaced")
    assert "referenced_blob_hash_invalid" in audit_run(tmp_path / "bytes" / "data", "run-1").blocks

    runtime, _ = _runtime(tmp_path / "malformed")
    _complete(runtime)
    (tmp_path / "malformed" / "data" / "runs" / "run-1" / "requests.jsonl").write_text("not-json\n")
    assert "malformed_persisted_runtime_evidence" in audit_run(tmp_path / "malformed" / "data", "run-1").blocks


def test_mutated_duplicate_attempt_id_is_blocked(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    _complete(runtime, retry=True)
    path = tmp_path / "data" / "runs" / "run-1" / "requests.jsonl"
    requests = _jsonl(path)
    requests[1]["attempt_id"] = requests[0]["attempt_id"]
    path.write_text("".join(json.dumps(record) + "\n" for record in requests))
    assert "duplicate_attempt_id" in audit_run(tmp_path / "data", "run-1").blocks


def test_transport_exception_keeps_auditable_attempt_and_uncaptured_send_is_rejected(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)

    def timeout(body: bytes, attempt_id: str) -> TransportResult:
        raise TimeoutError("fixture timeout")

    provider = CapturedProvider(timeout)
    with pytest.raises(RuntimeError, match="bound capture run"):
        provider.send(provider.prepare(RequestDraft(b"x")), "outside")
    snapshot = runtime.send_request(provider, b"draft", "call-1")
    run = runtime.seal(status="task_failed", stop_reason="provider_exception")
    assert snapshot.transport_status == "transport_exception"
    assert load_blob(tmp_path / "data", snapshot.sent_body_ref.blob_hash) == b"draft"
    assert run.status == "task_failed"
    assert audit_run(tmp_path / "data", "run-1").status == "PASS"


def test_attempt_set_mutations_block_through_persisted_audit(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path / "deleted")
    _complete(runtime)
    root = tmp_path / "deleted" / "data"
    _write_jsonl(root / "runs" / "run-1" / "requests.jsonl", [])
    assert "attempt_set_mismatch" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "orphan-request")
    _complete(runtime)
    root = tmp_path / "orphan-request" / "data"
    events = _jsonl(root / "runs" / "run-1" / "events.jsonl")
    event = next(item for item in events if item["kind"] == "request")
    payload = json.loads(load_blob(root, event["payload_ref"]["blob_hash"]))
    payload["attempt_id"] = "attempt:run-1:orphan"
    _replace_event_payload(root, events, event, payload)
    assert "orphan_request_event" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "orphan-terminal")
    _complete(runtime)
    root = tmp_path / "orphan-terminal" / "data"
    events = _jsonl(root / "runs" / "run-1" / "events.jsonl")
    event, payload = _response_payload(root, events)
    payload["attempt_id"] = "attempt:run-1:orphan"
    _replace_event_payload(root, events, event, payload)
    assert "orphan_terminal_event" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "duplicate-events")
    _complete(runtime)
    root = tmp_path / "duplicate-events" / "data"
    events = _jsonl(root / "runs" / "run-1" / "events.jsonl")
    request = next(item for item in events if item["kind"] == "request")
    terminal = next(item for item in events if item["kind"] == "response")
    _write_jsonl(root / "runs" / "run-1" / "events.jsonl", events + [request, terminal])
    blocks = audit_run(root, "run-1").blocks
    assert "duplicate_request_event" in blocks
    assert "duplicate_terminal_event" in blocks

    runtime, _ = _runtime(tmp_path / "wrong-logical-call")
    _complete(runtime)
    root = tmp_path / "wrong-logical-call" / "data"
    requests_path = root / "runs" / "run-1" / "requests.jsonl"
    requests = _jsonl(requests_path)
    requests[0]["logical_call_id"] = "other-logical-call"
    _write_jsonl(requests_path, requests)
    assert "attempt_logical_call_mismatch" in audit_run(root, "run-1").blocks


def test_usage_is_exactly_bound_to_raw_response(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path / "value")
    _complete(runtime)
    root = tmp_path / "value" / "data"
    events = _jsonl(root / "runs" / "run-1" / "events.jsonl")
    event, payload = _response_payload(root, events)
    payload["usage"]["value"]["input_tokens"] = 300000
    _replace_event_payload(root, events, event, payload)
    assert "provider_usage_value_mismatch" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "ref")
    _complete(runtime)
    root = tmp_path / "ref" / "data"
    events = _jsonl(root / "runs" / "run-1" / "events.jsonl")
    event, payload = _response_payload(root, events)
    alternate = ingest_runtime_bytes(b"other valid runtime blob", root, "run-1", "/other")
    payload["raw_usage_ref"] = alternate.model_dump()
    _replace_event_payload(root, events, event, payload)
    assert "provider_usage_reference_mismatch" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "locator")
    _complete(runtime)
    root = tmp_path / "locator" / "data"
    events = _jsonl(root / "runs" / "run-1" / "events.jsonl")
    event, payload = _response_payload(root, events)
    payload["raw_usage_ref"]["locator"] = "/id"
    payload["usage"]["refs"][0]["locator"] = "/id"
    _replace_event_payload(root, events, event, payload)
    assert "provider_usage_reference_mismatch" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "missing")
    _complete(runtime, with_usage=False)
    root = tmp_path / "missing" / "data"
    events = _jsonl(root / "runs" / "run-1" / "events.jsonl")
    event, payload = _response_payload(root, events)
    response_ref = payload["raw_response_ref"]
    payload["raw_usage_ref"] = {**response_ref, "locator": "/usage"}
    payload["usage"] = {"value": {"input_tokens": 0}, "status": "observed", "refs": [payload["raw_usage_ref"]]}
    _replace_event_payload(root, events, event, payload)
    assert "provider_usage_invented" in audit_run(root, "run-1").blocks


def test_repository_state_artifacts_are_closed_and_tree_identity_is_path_independent(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path / "initial")
    _complete(runtime)
    root = tmp_path / "initial" / "data"
    initial = json.loads((root / "runs" / "run-1" / "initial_state.json").read_text())
    initial["initial_tree_hash"] = "0" * 64
    (root / "runs" / "run-1" / "initial_state.json").write_text(json.dumps(initial))
    assert "repository_tree_hash_mismatch" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "final")
    _complete(runtime)
    root = tmp_path / "final" / "data"
    final = json.loads((root / "runs" / "run-1" / "final_state.json").read_text())
    final["final_tree_hash"] = "0" * 64
    final["producer_ref"]["trajectory_key"] = "other-run"
    (root / "runs" / "run-1" / "final_state.json").write_text(json.dumps(final))
    blocks = audit_run(root, "run-1").blocks
    assert "repository_tree_hash_mismatch" in blocks
    assert "repository_state_identity_mismatch" in blocks

    runtime, _ = _runtime(tmp_path / "sealed")
    _complete(runtime)
    root = tmp_path / "sealed" / "data"
    final = json.loads((root / "runs" / "run-1" / "final_state.json").read_text())
    final["tree_ref"]["locator"] = "/state/initial-tree"
    (root / "runs" / "run-1" / "final_state.json").write_text(json.dumps(final))
    assert "final_state_sealed_artifact_mismatch" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "state-ref")
    _complete(runtime)
    root = tmp_path / "state-ref" / "data"
    run = json.loads((root / "runs" / "run-1" / "run.json").read_text())
    run["initial_state_ref"] = run["sealed_artifact_ref"]
    (root / "runs" / "run-1" / "run.json").write_text(json.dumps(run))
    assert "repository_state_artifact_mismatch" in audit_run(root, "run-1").blocks

    first, second = tmp_path / "left-name", tmp_path / "right-name"
    first.mkdir(); second.mkdir()
    (first / "same.py").write_text("x\n"); (second / "same.py").write_text("x\n")
    assert initial_tree_manifest(first)[1] == initial_tree_manifest(second)[1]


def test_file_binding_occurrence_laundering_is_blocked(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    runtime.tools.read_file("a.py")
    runtime.tools.read_file("a.py")
    runtime.seal(status="completed")
    root = tmp_path / "data"
    bindings_path = root / "runs" / "run-1" / "file_bindings.jsonl"
    bindings = _jsonl(bindings_path)
    bindings[0]["read_event_id"] = bindings[1]["read_event_id"]
    _write_jsonl(bindings_path, bindings)
    assert "file_binding_occurrence_duplicate" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "sequence")
    runtime.tools.read_file("a.py"); runtime.tools.read_file("a.py"); runtime.seal(status="completed")
    root = tmp_path / "sequence" / "data"
    bindings_path = root / "runs" / "run-1" / "file_bindings.jsonl"
    bindings = _jsonl(bindings_path)
    bindings[0]["observed_seq"] = bindings[1]["observed_seq"]
    _write_jsonl(bindings_path, bindings)
    assert "file_binding_sequence_mismatch" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "locator")
    runtime.tools.read_file("a.py"); runtime.tools.read_file("a.py"); runtime.seal(status="completed")
    root = tmp_path / "locator" / "data"
    events = _jsonl(root / "runs" / "run-1" / "events.jsonl")
    finishes = [event for event in events if event["kind"] == "tool_finish"]
    payload = json.loads(load_blob(root, finishes[0]["payload_ref"]["blob_hash"]))
    payload["body_ref"]["locator"] = f"/tools/{finishes[1]['call_id']}/body"
    _replace_event_payload(root, events, finishes[0], payload)
    assert "file_binding_occurrence_mismatch" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "call-id")
    runtime.tools.read_file("a.py"); runtime.tools.read_file("a.py"); runtime.seal(status="completed")
    root = tmp_path / "call-id" / "data"
    events = _jsonl(root / "runs" / "run-1" / "events.jsonl")
    finishes = [event for event in events if event["kind"] == "tool_finish"]
    finishes[0]["call_id"] = finishes[1]["call_id"]
    _write_jsonl(root / "runs" / "run-1" / "events.jsonl", events)
    blocks = audit_run(root, "run-1").blocks
    assert "duplicate_tool_occurrence" in blocks
    assert "file_binding_occurrence_mismatch" in blocks


def _two_identical_attempts(tmp_path: Path) -> Path:
    runtime, _ = _runtime(tmp_path)
    provider = CapturedProvider(lambda body, attempt_id: TransportResult("ok", b'{"id":"same"}'))
    runtime.send_request(provider, b'{"prompt":"same"}', "call-1")
    runtime.send_request(provider, b'{"prompt":"same"}', "call-1")
    runtime.seal(status="completed")
    return tmp_path / "data"


@pytest.mark.parametrize("field", ["before_body_ref", "prepared_body_ref", "sent_body_ref"])
def test_request_evidence_occurrence_laundering_is_blocked(tmp_path: Path, field: str) -> None:
    root = _two_identical_attempts(tmp_path / field)
    path = root / "runs" / "run-1" / "requests.jsonl"
    requests = _jsonl(path)
    assert requests[0][field]["blob_hash"] == requests[1][field]["blob_hash"]
    requests[0][field]["locator"] = requests[1][field]["locator"]
    _write_jsonl(path, requests)
    blocks = audit_run(root, "run-1").blocks
    assert "request_occurrence_mismatch" in blocks


def test_physical_attempt_inventory_closes_direct_send_and_mutations(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path / "bypass")
    provider = CapturedProvider(lambda body, attempt_id: TransportResult("ok", b'{"id":"direct"}'))
    provider.bind_capture(
        data_root=runtime.data_root,
        run_id=runtime.run_id,
        producer_ref=runtime.producer_ref,
    )
    provider.send(provider.prepare(RequestDraft(b"direct")), "attempt:run-1:direct")
    runtime.seal(status="completed")
    blocks = audit_run(tmp_path / "bypass" / "data", "run-1").blocks
    assert "orphan_physical_attempt" in blocks

    root = _two_identical_attempts(tmp_path / "deleted")
    physical = root / "runs" / "run-1" / "physical_attempts"
    for path in physical.glob("*.json"):
        path.unlink()
    physical.rmdir()
    blocks = audit_run(root, "run-1").blocks
    assert "physical_attempt_inventory_mismatch" in blocks
    assert "normalized_attempt_without_physical_evidence" in blocks

    root = _two_identical_attempts(tmp_path / "sent-mismatch")
    physical = root / "runs" / "run-1" / "physical_attempts"
    first = physical / "physical-attempt:attempt:run-1:0:entered.json"
    second = physical / "physical-attempt:attempt:run-1:1:entered.json"
    first_record = json.loads(first.read_text())
    second_record = json.loads(second.read_text())
    assert first_record["sent_body_ref"]["blob_hash"] == second_record["sent_body_ref"]["blob_hash"]
    first_record["sent_body_ref"] = second_record["sent_body_ref"]
    first.write_text(json.dumps(first_record))
    assert "physical_attempt_sent_mismatch" in audit_run(root, "run-1").blocks

    root = _two_identical_attempts(tmp_path / "duplicate")
    physical = root / "runs" / "run-1" / "physical_attempts"
    original = physical / "physical-attempt:attempt:run-1:0:terminal.json"
    duplicate = physical / "duplicate.json"
    duplicate.write_bytes(original.read_bytes())
    assert "duplicate_physical_attempt" in audit_run(root, "run-1").blocks

    root = _two_identical_attempts(tmp_path / "terminal-deleted")
    physical = root / "runs" / "run-1" / "physical_attempts"
    (physical / "physical-attempt:attempt:run-1:0:terminal.json").unlink()
    assert "physical_attempt_terminal_missing" in audit_run(root, "run-1").blocks


def test_runtime_producer_and_config_references_are_closed(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path / "producer-file")
    _complete(runtime)
    root = tmp_path / "producer-file" / "data"
    (root / "runs" / "run-1" / "producer_manifest.json").write_text('{"producer_kind":"tampered"}')
    assert "runtime_producer_mismatch" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "producer-ref")
    _complete(runtime)
    root = tmp_path / "producer-ref" / "data"
    ref_path = root / "runs" / "run-1" / "producer_ref.json"
    ref = json.loads(ref_path.read_text())
    ref["blob_hash"] = "0" * 64
    ref_path.write_text(json.dumps(ref))
    assert "referenced_blob_missing" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "producer-run")
    _complete(runtime)
    root = tmp_path / "producer-run" / "data"
    ref_path = root / "runs" / "run-1" / "producer_ref.json"
    ref = json.loads(ref_path.read_text())
    ref["trajectory_key"] = "other-run"
    ref_path.write_text(json.dumps(ref))
    assert "wrong_run_evidence_reference" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "run-producer-ref")
    _complete(runtime)
    root = tmp_path / "run-producer-ref" / "data"
    run_path = root / "runs" / "run-1" / "run.json"
    run = json.loads(run_path.read_text())
    run["producer_ref"]["blob_hash"] = "0" * 64
    run_path.write_text(json.dumps(run))
    assert "runtime_producer_mismatch" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "producer-value")
    _complete(runtime)
    root = tmp_path / "producer-value" / "data"
    manifest = json.loads((root / "runs" / "run-1" / "producer_manifest.json").read_text())
    manifest["runtime_version"] = "tampered"
    ref = ingest_runtime_bytes(
        json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n",
        root,
        "run-1",
        "/producer-manifest",
    )
    (root / "runs" / "run-1" / "producer_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    (root / "runs" / "run-1" / "producer_ref.json").write_text(ref.model_dump_json())
    assert "runtime_producer_manifest_invalid" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "config-run")
    _complete(runtime)
    root = tmp_path / "config-run" / "data"
    run_path = root / "runs" / "run-1" / "run.json"
    run = json.loads(run_path.read_text())
    run["config_ref"]["trajectory_key"] = "other-run"
    run_path.write_text(json.dumps(run))
    assert "runtime_config_reference_mismatch" in audit_run(root, "run-1").blocks

    runtime, _ = _runtime(tmp_path / "config-blob")
    _complete(runtime)
    root = tmp_path / "config-blob" / "data"
    run_path = root / "runs" / "run-1" / "run.json"
    run = json.loads(run_path.read_text())
    run["config_ref"]["blob_hash"] = "0" * 64
    run_path.write_text(json.dumps(run))
    blocks = audit_run(root, "run-1").blocks
    assert "referenced_blob_missing" in blocks
    assert "runtime_config_reference_mismatch" in blocks

    root = _two_identical_attempts(tmp_path / "config-request")
    alternate = ingest_runtime_bytes(b'{"provider":"other"}', root, "run-1", "/other-config")
    requests_path = root / "runs" / "run-1" / "requests.jsonl"
    requests = _jsonl(requests_path)
    requests[1]["model_config_ref"] = alternate.model_dump()
    _write_jsonl(requests_path, requests)
    assert "request_config_reference_mismatch" in audit_run(root, "run-1").blocks


def test_deepseek_transport_and_bounded_smoke_remain_offline_and_captured(tmp_path: Path) -> None:
    sent: list[bytes] = []
    responses = [
        json.dumps(
            {
                "id": "provider-read",
                "choices": [{"message": {"content": "READ target.py"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            }
        ).encode(),
        json.dumps(
            {
                "id": "provider-final",
                "choices": [{"message": {"content": "def add(a, b): return a + b"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
            }
        ).encode(),
    ]

    def opener(request, timeout: float) -> _HTTPResponse:
        assert timeout == 30.0
        sent.append(request.data)
        assert request.get_header("Authorization") == "Bearer test-credential"
        return _HTTPResponse(responses.pop(0))

    runtime, _ = _runtime(tmp_path)
    (runtime.workspace / "target.py").write_text("def add(a, b):\n    # TODO\n    pass\n")
    provider = CapturedProvider(
        DeepSeekHTTPTransport(
            api_key="test-credential",
            base_url="https://api.deepseek.com",
            opener=opener,
        )
    )
    outcome = run_deepseek_add_smoke(runtime, provider, model="deepseek-v4-flash")
    assert outcome.physical_attempts == 2
    assert outcome.file_reads == 1
    assert outcome.final_response_observed
    assert outcome.run.status == "task_failed"
    assert "# TODO" in (runtime.workspace / "target.py").read_text()
    assert outcome.run.capabilities["runtime_level"] == "engineering_fixture_only"
    assert audit_run(tmp_path / "data", "run-1").status == "PASS"
    assert all(json.loads(body)["model"] == "deepseek-v4-flash" for body in sent)
    persisted = "\n".join(
        path.read_text(errors="ignore")
        for path in (tmp_path / "data").rglob("*")
        if path.is_file()
    )
    assert "test-credential" not in persisted


def test_plain_code_response_never_modifies_workspace_or_completes_run(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    target = runtime.workspace / "target.py"
    target.write_text("def add(a, b):\n    pass\n")
    before = target.read_bytes()
    response = b'{"choices":[{"message":{"content":"def add(a, b): return a + b"}}]}'
    outcome = run_deepseek_add_smoke(
        runtime,
        CapturedProvider(lambda body, attempt: TransportResult("ok", response)),
        model="deepseek-v4-flash",
    )
    assert target.read_bytes() == before
    assert outcome.run.status == "task_failed"
    assert outcome.run.stop_reason == "agent_did_not_modify_workspace"


def test_public_task_instruction_is_the_actual_sent_user_message(tmp_path: Path) -> None:
    marker = "UNIQUE_TASK_MARKER_12345"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "target.py").write_text("def add(a, b):\n    pass\n")
    sent: list[bytes] = []

    def transport(body: bytes, attempt_id: str) -> TransportResult:
        del attempt_id
        sent.append(body)
        return TransportResult(
            "ok",
            b'{"choices":[{"message":{"content":"FINAL"}}]}',
        )

    runtime = CapturedRuntime(
        data_root=tmp_path / "data",
        run_id="task-binding-run",
        task=RuntimeTask("public/add", marker),
        workspace=workspace,
        config_bytes=b'{"provider":"engineering-fixture"}',
    )
    run_deepseek_add_smoke(
        runtime,
        CapturedProvider(transport),
        model="deepseek-v4-flash",
    )

    assert len(sent) == 1
    request = json.loads(sent[0])
    user_messages = [message["content"] for message in request["messages"] if message["role"] == "user"]
    system_messages = [
        message["content"] for message in request["messages"] if message["role"] == "system"
    ]
    assert user_messages == [marker]
    assert "Inspect target.py and implement add(a, b)." not in user_messages
    assert len(system_messages) == 1
    for command in ("READ target.py", "WRITE target.py", "TEST", "FINAL"):
        assert command in system_messages[0]
    assert "exactly ONE command per turn" in system_messages[0]
    assert "Returning Python code without WRITE does not modify the workspace" in system_messages[0]


def test_duplicate_read_context_blocks_bind_each_exact_occurrence(tmp_path: Path) -> None:
    responses = [
        b'{"choices":[{"message":{"content":"READ target.py"}}]}',
        b'{"choices":[{"message":{"content":"READ target.py"}}]}',
        b'{"choices":[{"message":{"content":"WRITE target.py\\ndef add(a, b):\\n    return a + b\\n"}}]}',
    ]
    runtime, _ = _runtime(tmp_path)
    (runtime.workspace / "target.py").write_text("def add(a, b):\n    pass\n")
    run_deepseek_add_smoke(
        runtime,
        CapturedProvider(lambda body, attempt: TransportResult("ok", responses.pop(0))),
        model="deepseek-v4-flash",
    )
    bindings = _jsonl(tmp_path / "data" / "runs" / "run-1" / "file_bindings.jsonl")
    assert bindings[0]["file_sha256"] == bindings[1]["file_sha256"]
    assert bindings[0]["read_event_id"] != bindings[1]["read_event_id"]
    requests = _jsonl(tmp_path / "data" / "runs" / "run-1" / "requests.jsonl")
    blocks = [
        block
        for block in requests[2]["ordered_blocks"]
        if block["tool_call_id"]
    ]
    assert [block["origin_event_id"] for block in blocks] == [
        bindings[0]["read_event_id"],
        bindings[1]["read_event_id"],
    ]
    assert blocks[0]["tool_call_id"] != blocks[1]["tool_call_id"]
    assert audit_run(tmp_path / "data", "run-1").status == "PASS"


def test_cli_attempt_acceptance_uses_frozen_hard_maximum() -> None:
    config = {"budget": {"hard_max_physical_attempts": 5, "target_physical_attempts": 2}}
    assert _within_attempt_budget(1, config)
    assert _within_attempt_budget(5, config)
    assert not _within_attempt_budget(0, config)
    assert not _within_attempt_budget(6, config)


def test_deepseek_transport_exception_uses_the_existing_failure_path(tmp_path: Path) -> None:
    def timeout(request, timeout_seconds: float) -> _HTTPResponse:
        del request, timeout_seconds
        raise TimeoutError("offline timeout")

    runtime, _ = _runtime(tmp_path)
    provider = CapturedProvider(
        DeepSeekHTTPTransport(
            api_key="test-credential",
            base_url="https://api.deepseek.com",
            opener=timeout,
        )
    )
    snapshot = runtime.send_request(
        provider,
        serialize_deepseek_chat_request(
            model="deepseek-v4-flash", messages=[{"role": "user", "content": "hello"}]
        ),
        "deepseek-timeout",
    )
    runtime.seal(status="task_failed", stop_reason="provider_exception")
    assert snapshot.transport_status == "transport_exception"
    assert audit_run(tmp_path / "data", "run-1").status == "PASS"


def test_add_loop_edits_workspace_maps_context_and_seals_reconstructible_artifact(tmp_path: Path) -> None:
    responses = [
        b'{"choices":[{"message":{"content":"READ target.py"}}]}',
        b'{"choices":[{"message":{"content":"WRITE target.py\\ndef add(a, b):\\n    return a + b\\n"}}]}',
    ]
    runtime, _ = _runtime(tmp_path)
    (runtime.workspace / "target.py").write_text("def add(a, b):\n    pass\n")
    outcome = run_deepseek_add_smoke(
        runtime,
        CapturedProvider(lambda body, attempt: TransportResult("ok", responses.pop(0))),
        model="deepseek-v4-flash",
    )
    assert outcome.run.status == "completed"
    assert "return a + b" in (runtime.workspace / "target.py").read_text()
    snapshots = _jsonl(tmp_path / "data" / "runs" / "run-1" / "requests.jsonl")
    assert snapshots[1]["ordered_blocks"]
    tool_blocks = [block for block in snapshots[1]["ordered_blocks"] if block["tool_call_id"]]
    assert len(tool_blocks) == 1
    assert tool_blocks[0]["file_binding"]["read_event_id"] == tool_blocks[0]["origin_event_id"]
    shutil.rmtree(runtime.workspace)
    private = tmp_path / "private.json"
    private.write_text(json.dumps({"tests": [{"args": [1, 2], "expected": 3}]}))
    result = LocalAddEvaluator(data_root=tmp_path / "data", code_revision="a" * 40).evaluate(outcome.run, str(private))
    assert result.status == "completed" and result.resolved.value is True
    assert audit_run(tmp_path / "data", "run-1").status == "PASS"


def test_submission_error_is_task_failure_and_journal_survives_before_seal(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    runtime.tools.read_file("a.py")
    assert (tmp_path / "data" / "runs" / "run-1" / "events.journal.jsonl").read_text()
    runtime.tools.write_file("a.py", "def broken(:\n")
    run = runtime.seal(status="completed")
    private = tmp_path / "private.json"
    private.write_text(json.dumps({"tests": [{"args": [1, 2], "expected": 3}]}))
    result = LocalAddEvaluator(data_root=tmp_path / "data", code_revision="a" * 40).evaluate(run, str(private))
    assert result.status == "completed"
    assert result.resolved.value is False


def test_usage_ledger_is_persisted_and_rebuildable(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    _complete(runtime)
    aggregate = json.loads((tmp_path / "data" / "runs" / "run-1" / "usage_aggregate.json").read_text())
    assert aggregate["physical_attempt_count"] == 1
    assert aggregate["usage_complete"] is False
    assert (tmp_path / "data" / "runs" / "run-1" / "usage_ledger.jsonl").read_text()


def test_private_add_evaluator_is_sealed_only_persisted_and_fail_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"; workspace.mkdir()
    (workspace / "target.py").write_text("def add(a, b):\n    # TODO\n    pass\n")
    runtime = CapturedRuntime(data_root=tmp_path / "data", run_id="eval-run", task=RuntimeTask("public/add", "public"), workspace=workspace, config_bytes=b"{}")
    private_spec = tmp_path / "private.json"
    private_spec.write_text(json.dumps({"private_marker": "PRIVATE_EVALUATOR_ONLY", "tests": [{"args": [1, 2], "expected": 3}, {"args": [-1, 1], "expected": 0}, {"args": [0, 0], "expected": 0}]}))
    evaluator = LocalAddEvaluator(
        data_root=tmp_path / "data", sealed_workspace=workspace, code_revision="a" * 40
    )
    with pytest.raises(EvaluationHandoffRejected):
        evaluator.evaluate(
            Run(
                kind="run", id="eval-run", producer_ref=runtime.producer_ref, task_id="public/add",
                config_ref=runtime.producer_ref, capabilities={}, initial_state_ref=runtime.producer_ref,
                status="running", events_ref=runtime.producer_ref,
            ),
            str(private_spec),
        )
    run = runtime.seal(status="completed")
    result = evaluator.evaluate(run, str(private_spec))
    assert result.status == "completed"
    assert result.tests_executed.value == 3
    assert result.passed.value == 0
    assert result.failed.value == 3
    assert result.resolved.value is False
    assert audit_evaluation(tmp_path / "data", "eval-run", str(private_spec)).status == "PASS"
    assert not (workspace / "__pycache__").exists()

    result_path = tmp_path / "data" / "evaluations" / "eval-run" / "evaluation_result.json"
    tampered = json.loads(result_path.read_text()); tampered["resolved"]["value"] = True; result_path.write_text(json.dumps(tampered))
    assert "evaluation_fact_mismatch" in audit_evaluation(tmp_path / "data", "eval-run", str(private_spec)).blocks

    result_path.write_text(result.model_dump_json())
    tampered = json.loads(result_path.read_text()); tampered["submitted_artifact_hash"] = "0" * 64; result_path.write_text(json.dumps(tampered))
    assert "evaluation_run_binding_mismatch" in audit_evaluation(tmp_path / "data", "eval-run", str(private_spec)).blocks

    result_path.write_text(result.model_dump_json())
    ingest_runtime_bytes(private_spec.read_bytes(), tmp_path / "data", "eval-run", "/injected")
    assert "evaluator_private_data_leakage" in audit_evaluation(tmp_path / "data", "eval-run", str(private_spec)).blocks

    result_path.write_text(result.model_dump_json())
    blob = tmp_path / "data" / "blobs" / result.raw_result_ref.blob_hash
    blob.write_bytes(b"tampered")
    assert "referenced_blob_hash_invalid" in audit_evaluation(tmp_path / "data", "eval-run", str(private_spec)).blocks

    blob.write_bytes(json.dumps({"status": "completed", "patch_valid": False, "tests_executed": 3, "passed": 0, "failed": 3, "resolved": False}, sort_keys=True).encode())
    tampered = json.loads(result_path.read_text())
    tampered["raw_result_ref"] = ingest_runtime_bytes(b"other", tmp_path / "data", "eval-run", "/other").model_dump()
    result_path.write_text(json.dumps(tampered))
    assert "evaluation_raw_reference_mismatch" in audit_evaluation(tmp_path / "data", "eval-run", str(private_spec)).blocks


def _fresh_evaluation(root: Path) -> tuple[Path, Path]:
    """Create a sealed runtime plus evaluator artifacts for persisted mutations."""

    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "target.py").write_text("def add(a, b):\n    # TODO\n    pass\n")
    runtime = CapturedRuntime(
        data_root=root / "data",
        run_id="eval-run",
        task=RuntimeTask("public/add", "public"),
        workspace=workspace,
        config_bytes=b"{}",
    )
    private_spec = root / "private.json"
    private_spec.write_text(json.dumps({"tests": [{"args": [1, 2], "expected": 3}]}))
    run = runtime.seal(status="completed")
    LocalAddEvaluator(
        data_root=root / "data", sealed_workspace=workspace, code_revision="a" * 40
    ).evaluate(run, str(private_spec))
    assert audit_evaluation(root / "data", "eval-run", str(private_spec)).status == "PASS"
    return root / "data", private_spec


def _replace_evaluator_producer(root: Path, private_spec: Path, manifest: dict[str, str]) -> None:
    """Make all persisted producer links agree, so a targeted invariant is tested."""

    content = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    ref = ingest_evaluator_bytes(content, root, "eval-run", "/evaluation/producer-manifest")
    evaluation_root = root / "evaluations" / "eval-run"
    (evaluation_root / "producer_manifest.json").write_bytes(content)
    (evaluation_root / "producer_ref.json").write_text(ref.model_dump_json())
    value = json.loads((evaluation_root / "evaluation_result.json").read_text())
    value["producer_ref"] = ref.model_dump()
    (evaluation_root / "evaluation_result.json").write_text(json.dumps(value))
    assert private_spec.exists()


def test_evaluator_producer_and_private_spec_identity_mutations_block(tmp_path: Path) -> None:
    # Result producer ref cannot select another valid evaluator-domain blob.
    root, private_spec = _fresh_evaluation(tmp_path / "result-ref")
    alternate = ingest_evaluator_bytes(b"alternate valid evaluator blob", root, "eval-run", "/evaluation/producer-manifest")
    result_path = root / "evaluations" / "eval-run" / "evaluation_result.json"
    value = json.loads(result_path.read_text()); value["producer_ref"] = alternate.model_dump(); result_path.write_text(json.dumps(value))
    assert "evaluation_producer_mismatch" in audit_evaluation(root, "eval-run", str(private_spec)).blocks

    # The persisted ref is run- and locator-bound, independently of its blob hash.
    root, private_spec = _fresh_evaluation(tmp_path / "ref-run")
    ref_path = root / "evaluations" / "eval-run" / "producer_ref.json"
    value = json.loads(ref_path.read_text()); value["trajectory_key"] = "other-run"; ref_path.write_text(json.dumps(value))
    assert "evaluation_producer_mismatch" in audit_evaluation(root, "eval-run", str(private_spec)).blocks
    root, private_spec = _fresh_evaluation(tmp_path / "ref-locator")
    ref_path = root / "evaluations" / "eval-run" / "producer_ref.json"
    value = json.loads(ref_path.read_text()); value["locator"] = "/other"; ref_path.write_text(json.dumps(value))
    assert "evaluation_producer_mismatch" in audit_evaluation(root, "eval-run", str(private_spec)).blocks

    # File/blob divergence is not repaired by parsing a plausible manifest file.
    root, private_spec = _fresh_evaluation(tmp_path / "manifest-file")
    (root / "evaluations" / "eval-run" / "producer_manifest.json").write_text('{"producer_kind":"tampered"}\n')
    assert "evaluation_producer_mismatch" in audit_evaluation(root, "eval-run", str(private_spec)).blocks

    def valid_manifest(spec_hash: str) -> dict[str, str]:
        return {
            "producer_kind": "acr_local_add_evaluator",
            "schema_version": "1.0",
            "evaluator_version": "local_add_evaluator_v1",
            "code_revision": "a" * 40,
            "private_spec_sha256": spec_hash,
        }

    # The static evaluator version and EvaluationResult revision are both frozen.
    root, private_spec = _fresh_evaluation(tmp_path / "version")
    manifest = valid_manifest("0" * 64); manifest["evaluator_version"] = "local_add_evaluator_v2"
    _replace_evaluator_producer(root, private_spec, manifest)
    assert "evaluation_producer_mismatch" in audit_evaluation(root, "eval-run", str(private_spec)).blocks
    root, private_spec = _fresh_evaluation(tmp_path / "revision")
    result_path = root / "evaluations" / "eval-run" / "evaluation_result.json"
    value = json.loads(result_path.read_text()); value["evaluator_revision"] = "local_add_evaluator_v2"; result_path.write_text(json.dumps(value))
    assert "evaluation_producer_mismatch" in audit_evaluation(root, "eval-run", str(private_spec)).blocks

    # The hash in a fully self-consistent producer artifact still must name the
    # exact private spec supplied to the audit.
    root, private_spec = _fresh_evaluation(tmp_path / "spec-hash")
    _replace_evaluator_producer(root, private_spec, valid_manifest("0" * 64))
    assert "evaluation_private_spec_mismatch" in audit_evaluation(root, "eval-run", str(private_spec)).blocks
    root, private_spec = _fresh_evaluation(tmp_path / "spec-replaced")
    private_spec.write_text(json.dumps({"tests": [{"args": [5, 5], "expected": 10}]}))
    assert "evaluation_private_spec_mismatch" in audit_evaluation(root, "eval-run", str(private_spec)).blocks

    root, private_spec = _fresh_evaluation(tmp_path / "code-revision")
    manifest = valid_manifest(hashlib.sha256(private_spec.read_bytes()).hexdigest())
    manifest["code_revision"] = "not-a-revision"
    _replace_evaluator_producer(root, private_spec, manifest)
    assert "evaluation_producer_mismatch" in audit_evaluation(root, "eval-run", str(private_spec)).blocks
