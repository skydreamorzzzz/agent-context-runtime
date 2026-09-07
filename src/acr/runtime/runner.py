"""Minimal synchronous M2 capture runtime, deliberately not an agent framework."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from acr.adapters.provider import CapturedProvider, RequestDraft
from acr.contracts import Event, EvidenceRef, Fact, RepositoryState, RequestSnapshot, Run
from acr.runtime.tools import RuntimeTools
from acr.state import initial_tree_manifest, verified_workspace
from acr.store import (
    ingest_runtime_bytes,
    persist_run_json,
    persist_run_jsonl,
)


class RunSealedError(RuntimeError):
    """Raised when code tries to append ordinary runtime evidence after seal."""


@dataclass(frozen=True)
class RuntimeTask:
    """Public runtime input only; private evaluator data has no field here."""

    task_id: str
    public_instruction: str


class CapturedRuntime:
    """A tiny serial recorder used for the M2 engineering-only wiring fixture."""

    def __init__(
        self,
        *,
        data_root: Path,
        run_id: str,
        task: RuntimeTask,
        workspace: Path,
        config_bytes: bytes,
        private_eval_root: Path | None = None,
        image_digest: str | None = None,
    ) -> None:
        forbidden = (data_root,) + ((private_eval_root,) if private_eval_root else ())
        self.workspace = verified_workspace(workspace, forbidden_roots=forbidden)
        self.data_root = data_root
        self.run_id = run_id
        self.task = task
        self._sealed = False
        self._events: list[Event] = []
        self._snapshots: list[RequestSnapshot] = []
        self._event_seq = 0
        self._attempt_seq = 0
        self._producer_ref = self._persist_producer()
        self._config_ref = ingest_runtime_bytes(config_bytes, data_root, run_id, "/config")
        tree, tree_hash = initial_tree_manifest(self.workspace)
        self._initial_tree_ref = ingest_runtime_bytes(
            json.dumps(tree, sort_keys=True).encode(), data_root, run_id, "/state/initial-tree"
        )
        image = (
            Fact[str](value=image_digest, status="observed", refs=[self._config_ref])
            if image_digest
            else Fact[str](status="unknown", reason="runtime_image_digest_not_observed")
        )
        self._initial_state = RepositoryState(
            kind="repository_state",
            id=f"state:{run_id}:initial",
            producer_ref=self._producer_ref,
            run_id=run_id,
            initial_tree_hash=tree_hash,
            tree_ref=self._initial_tree_ref,
            image_digest=image,
            observed_seq=0,
            files=[],
            state_caps={
                "initial_repository": "verified",
                "file_binding": "read_bound",
                "execution_restore": "unsupported",
            },
        )
        persist_run_json(data_root, run_id, "initial_state.json", self._initial_state)
        self._initial_state_ref = ingest_runtime_bytes(
            self._initial_state.model_dump_json(indent=2).encode() + b"\n",
            data_root,
            run_id,
            "/initial_state.json",
        )
        self.tools = RuntimeTools(self.workspace, data_root, run_id, self.record_event)

    @property
    def initial_state(self) -> RepositoryState:
        return self._initial_state

    @property
    def sealed(self) -> bool:
        return self._sealed

    def _persist_producer(self) -> EvidenceRef:
        code_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        manifest = {
            "producer_kind": "acr_runtime_capture",
            "code_revision": code_revision,
            "schema_version": "1.0",
            "runtime_version": "m2_capture_v1",
        }
        raw = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
        ref = ingest_runtime_bytes(raw, self.data_root, self.run_id, "/producer-manifest")
        persist_run_json(self.data_root, self.run_id, "producer_manifest.json", manifest)
        persist_run_json(self.data_root, self.run_id, "producer_ref.json", ref)
        return ref

    def record_event(
        self,
        kind: str,
        call_id: str | None,
        payload: dict[str, object],
        completed: bool,
    ) -> tuple[str, int]:
        if self._sealed:
            raise RunSealedError("cannot record normal runtime evidence after sealing")
        event_seq = self._event_seq
        self._event_seq += 1
        event_id = f"event:{self.run_id}:{event_seq}"
        payload_ref = ingest_runtime_bytes(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
            self.data_root,
            self.run_id,
            f"/events/{event_seq}/payload",
        )
        now = datetime.now(timezone.utc)
        event = Event(
            kind=kind,
            id=event_id,
            producer_ref=self._producer_ref,
            run_id=self.run_id,
            event_seq=event_seq,
            call_id=call_id,
            payload_ref=payload_ref,
            available_seq=event_seq if completed else None,
            start=now,
            end=now if completed else None,
        )
        self._events.append(event)
        return event_id, event_seq

    def send_request(
        self,
        provider: CapturedProvider,
        body: bytes,
        logical_call_id: str,
    ) -> RequestSnapshot:
        if self._sealed:
            raise RunSealedError("cannot send after seal")
        attempt_id = f"attempt:{self.run_id}:{self._attempt_seq}"
        self._attempt_seq += 1
        prepared = provider.prepare(RequestDraft(body=body))
        provider.bind_capture(data_root=self.data_root, run_id=self.run_id)
        attempt = provider.send(prepared, attempt_id)
        cutoff_seq = max((event.available_seq or 0 for event in self._events), default=0)
        snapshot = RequestSnapshot(
            kind="request_snapshot",
            id=f"request:{attempt_id}",
            producer_ref=self._producer_ref,
            run_id=self.run_id,
            logical_call_id=logical_call_id,
            attempt_id=attempt_id,
            cutoff_seq=cutoff_seq,
            before_body_ref=attempt.before_body_ref,
            prepared_body_ref=attempt.prepared_body_ref,
            sent_body_ref=attempt.sent_body_ref,
            ordered_blocks=[],
            model_config_ref=self._config_ref,
            transport_status=attempt.transport_status,
            provider_request_id=attempt.provider_request_id,
        )
        self._snapshots.append(snapshot)
        self.record_event(
            "request",
            logical_call_id,
            {
                "attempt_id": attempt_id,
                "before_body_ref": attempt.before_body_ref.model_dump(),
                "prepared_body_ref": attempt.prepared_body_ref.model_dump(),
                "sent_body_ref": attempt.sent_body_ref.model_dump(),
                "transport_status": attempt.transport_status,
                "logical_call_id": logical_call_id,
            },
            True,
        )
        terminal_kind = "provider_failure" if attempt.failure_ref else "response"
        self.record_event(
            terminal_kind,
            logical_call_id,
            {
                "attempt_id": attempt_id,
                "raw_response_ref": (
                    attempt.raw_response_ref.model_dump() if attempt.raw_response_ref else None
                ),
                "failure_ref": attempt.failure_ref.model_dump() if attempt.failure_ref else None,
                "raw_usage_ref": attempt.raw_usage_ref.model_dump() if attempt.raw_usage_ref else None,
                "usage": attempt.usage.model_dump(),
                "transport_status": attempt.transport_status,
                "provider_request_id": attempt.provider_request_id,
                "logical_call_id": logical_call_id,
            },
            True,
        )
        return snapshot

    def seal(self, *, status: str, stop_reason: str | None = None) -> Run:
        if self._sealed:
            raise RunSealedError("run is already sealed")
        self.record_event("run_stop", None, {"status": status, "stop_reason": stop_reason}, True)
        events_bytes = b"".join(event.model_dump_json().encode() + b"\n" for event in self._events)
        events_ref = ingest_runtime_bytes(events_bytes, self.data_root, self.run_id, "/events.jsonl")
        persist_run_jsonl(self.data_root, self.run_id, "events.jsonl", self._events)
        persist_run_jsonl(self.data_root, self.run_id, "requests.jsonl", self._snapshots)
        persist_run_jsonl(self.data_root, self.run_id, "file_bindings.jsonl", self.tools.bindings)
        final_tree, final_hash = initial_tree_manifest(self.workspace)
        final_tree_bytes = json.dumps(final_tree, sort_keys=True).encode()
        final_ref = ingest_runtime_bytes(
            final_tree_bytes, self.data_root, self.run_id, "/state/final-tree"
        )
        final_state = self._initial_state.model_copy(
            update={
                "id": f"state:{self.run_id}:final",
                "state_phase": "final",
                "initial_tree_hash": None,
                "final_tree_hash": final_hash,
                "tree_ref": final_ref,
                "observed_seq": self._events[-1].event_seq,
                "files": self.tools.bindings,
            }
        )
        persist_run_json(self.data_root, self.run_id, "final_state.json", final_state)
        final_state_ref = ingest_runtime_bytes(
            final_state.model_dump_json(indent=2).encode() + b"\n",
            self.data_root,
            self.run_id,
            "/final_state.json",
        )
        run = Run(
            kind="run",
            id=self.run_id,
            producer_ref=self._producer_ref,
            task_id=self.task.task_id,
            config_ref=self._config_ref,
            capabilities={
                "runtime_level": "engineering_fixture_only",
                "initial_repository": "verified",
                "file_binding": "read_bound",
                "execution_restore": "unsupported",
                "evaluation": "not_run",
            },
            initial_state_ref=self._initial_state_ref,
            start=self._events[0].start if self._events else None,
            end=datetime.now(timezone.utc),
            status=status,
            stop_reason=stop_reason,
            events_ref=events_ref,
            final_state_ref=final_state_ref,
            sealed_artifact_ref=final_ref,
            sealed_artifact_hash=hashlib.sha256(final_tree_bytes).hexdigest(),
        )
        persist_run_json(self.data_root, self.run_id, "run.json", run)
        self._sealed = True
        return run


def run_scripted_capture(
    runtime: CapturedRuntime,
    script: Callable[[CapturedRuntime], None],
    *,
    status: str = "completed",
) -> Run:
    """Engineering-only fixture harness; never a real provider/task claim."""

    script(runtime)
    return runtime.seal(status=status)
