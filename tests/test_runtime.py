"""M2 persisted trusted-capture tests using an explicitly engineering-only transport."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acr.adapters.provider import CapturedProvider, RequestDraft, TransportResult
from acr.audit import audit_run
from acr.contracts import Run
from acr.evaluation import EvaluationHandoffRejected, require_sealed_run
from acr.runtime.runner import CapturedRuntime, RunSealedError, RuntimeTask
from acr.state import WorkspaceViolation, initial_tree_manifest
from acr.store import ingest_runtime_bytes, load_blob


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
