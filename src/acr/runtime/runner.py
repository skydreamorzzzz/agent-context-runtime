"""Minimal synchronous M2 capture runtime, deliberately not an agent framework."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from acr.accounting import usage_entries
from acr.adapters.provider import (
    CapturedAttempt,
    CapturedProvider,
    RequestDraft,
    extract_deepseek_message_content,
    serialize_deepseek_chat_request,
)
from acr.contracts import (
    ContextBlock,
    Event,
    EvidenceRef,
    Fact,
    FileBinding,
    FileComparison,
    InformationLabel,
    RepositoryState,
    RequestSnapshot,
    Run,
)
from acr.runtime.tools import RuntimeTools
from acr.state import _compare_file_at_seq, initial_tree_manifest, verified_workspace
from acr.store import (
    append_run_jsonl,
    ingest_bytes,
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


@dataclass(frozen=True)
class ConversationMessage:
    """One request message plus its optional exact tool occurrence."""

    role: str
    content: str
    origin_event_id: str | None = None
    tool_call_id: str | None = None
    file_binding: FileBinding | None = None
    provenance_ref: EvidenceRef | None = None

    def wire(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


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
        runtime_level: str = "engineering_fixture_only",
    ) -> None:
        forbidden = (data_root,) + ((private_eval_root,) if private_eval_root else ())
        self.workspace = verified_workspace(workspace, forbidden_roots=forbidden)
        self.data_root = data_root
        self.run_id = run_id
        self.task = task
        self._runtime_level = runtime_level
        self._sealed = False
        self._events: list[Event] = []
        self._snapshots: list[RequestSnapshot] = []
        self._event_seq = 0
        self._attempt_seq = 0
        self._last_attempt: CapturedAttempt | None = None
        self._last_terminal_event_id: str | None = None
        self._last_terminal_seq: int | None = None
        self._attempt_usages: list[tuple[str, Fact[dict], EvidenceRef | None]] = []
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

    @property
    def producer_ref(self) -> EvidenceRef:
        return self._producer_ref

    @property
    def last_attempt(self) -> CapturedAttempt | None:
        """Most recent captured physical attempt for this synchronous runtime."""

        return self._last_attempt

    @property
    def last_terminal_event_id(self) -> str | None:
        return self._last_terminal_event_id

    @property
    def last_terminal_seq(self) -> int | None:
        return self._last_terminal_seq

    @property
    def event_prefix(self) -> tuple[Event, ...]:
        """Return the recorded prefix without exposing mutable runtime state."""

        return tuple(self._events)

    def public_context_ref(
        self, content: str, *, source_id: str, trajectory_key: str, locator: str
    ) -> EvidenceRef:
        """Persist an exact authorized public/config context source."""

        return ingest_bytes(
            content.encode(), self.data_root, source_id, trajectory_key, locator
        ).model_copy(update={"labels": [InformationLabel(scope="public")]})

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
        append_run_jsonl(self.data_root, self.run_id, "events.journal.jsonl", event)
        return event_id, event_seq

    def compare_bound_file(
        self, binding: FileBinding, binding_ref: EvidenceRef
    ) -> FileComparison:
        """Re-read a bound file and attest its actual observation sequence."""

        if self._sealed:
            raise RunSealedError("cannot check file state after sealing")
        reserved_seq = self._event_seq
        comparison = _compare_file_at_seq(
            self.workspace,
            binding,
            binding_ref,
            data_root=self.data_root,
            run_id=self.run_id,
            checked_seq=reserved_seq,
        )
        _, event_seq = self.record_event(
            "state_check",
            binding.read_event_id,
            {
                "binding_ref": comparison.binding_ref.model_dump(),
                "repo_relative_path": binding.repo_relative_path,
                "historical_file_sha256": binding.file_sha256,
                "current_file_ref": (
                    comparison.current_file_ref.model_dump()
                    if comparison.current_file_ref is not None
                    else None
                ),
                "current_file_sha256": comparison.current_file_sha256,
                "status": comparison.status,
                "reason": comparison.reason,
            },
            True,
        )
        if event_seq != comparison.checked_seq:
            raise RuntimeError("state-check sequence reservation changed")
        return comparison

    def context_blocks(
        self, request_id: str, messages: list[ConversationMessage]
    ) -> list[ContextBlock]:
        """Map every serialized message occurrence to its prior evidence boundary."""

        blocks: list[ContextBlock] = []
        for index, message in enumerate(messages):
            content = message.content.encode()
            if message.origin_event_id is None or message.provenance_ref is None:
                raise ValueError("context message requires explicit occurrence provenance")
            block_type = (
                "tool_result"
                if message.tool_call_id
                else "system_prompt"
                if message.role == "system"
                else "assistant_response"
                if message.role == "assistant"
                else "task_instruction"
            )
            blocks.append(ContextBlock(
                kind="context_block", id=f"block:{request_id}:{index}", producer_ref=self._producer_ref,
                provenance_ref=message.provenance_ref,
                request_id=request_id, occurrence_id=f"{request_id}:block:{index}", origin_event_id=message.origin_event_id,
                role=message.role, type=block_type,
                tool_call_id=message.tool_call_id,
                body_pointer=f"/messages/{index}/content", content_hash=hashlib.sha256(content).hexdigest(),
                complete=True,
                file_binding=message.file_binding,
            ))
        return blocks

    def send_request(
        self,
        provider: CapturedProvider,
        body: bytes,
        logical_call_id: str,
        ordered_blocks: list[ContextBlock] | None = None,
    ) -> RequestSnapshot:
        if self._sealed:
            raise RunSealedError("cannot send after seal")
        attempt_id = f"attempt:{self.run_id}:{self._attempt_seq}"
        self._attempt_seq += 1
        prepared = provider.prepare(RequestDraft(body=body))
        provider.bind_capture(
            data_root=self.data_root,
            run_id=self.run_id,
            producer_ref=self._producer_ref,
        )
        attempt = provider.send(prepared, attempt_id)
        self._last_attempt = attempt
        self._attempt_usages.append((attempt_id, attempt.usage, attempt.raw_usage_ref))
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
            ordered_blocks=ordered_blocks or [],
            model_config_ref=self._config_ref,
            transport_status=attempt.transport_status,
            provider_request_id=attempt.provider_request_id,
        )
        self._snapshots.append(snapshot)
        append_run_jsonl(self.data_root, self.run_id, "requests.journal.jsonl", snapshot)
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
        terminal_event_id, terminal_seq = self.record_event(
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
        self._last_terminal_event_id = terminal_event_id
        self._last_terminal_seq = terminal_seq
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
        entries, aggregate = usage_entries(
            run_id=self.run_id, producer_ref=self._producer_ref, attempts=self._attempt_usages
        )
        persist_run_jsonl(self.data_root, self.run_id, "usage_ledger.jsonl", entries)
        persist_run_json(self.data_root, self.run_id, "usage_aggregate.json", aggregate)
        final_tree, final_hash = initial_tree_manifest(self.workspace)
        final_tree_bytes = json.dumps(final_tree, sort_keys=True).encode()
        final_ref = ingest_runtime_bytes(final_tree_bytes, self.data_root, self.run_id, "/state/final-tree")
        sealed_files = []
        for item in final_tree["files"]:
            path = str(item["path"])
            raw = (self.workspace / path).read_bytes()
            sealed_files.append({**item, "body_ref": ingest_runtime_bytes(raw, self.data_root, self.run_id, f"/sealed/files/{path}").model_dump()})
        sealed_bytes = json.dumps({"files": sealed_files}, sort_keys=True, separators=(",", ":")).encode()
        sealed_ref = ingest_runtime_bytes(sealed_bytes, self.data_root, self.run_id, "/sealed-artifact")
        persist_run_json(self.data_root, self.run_id, "sealed_artifact.json", {"files": sealed_files})
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
                "runtime_level": self._runtime_level,
                "initial_repository": "verified",
                "file_binding": "read_bound",
                "execution_restore": "unsupported",
                "evaluation": "not_run",
                "workspace_identity": hashlib.sha256(str(self.workspace).encode()).hexdigest(),
            },
            initial_state_ref=self._initial_state_ref,
            start=self._events[0].start if self._events else None,
            end=datetime.now(timezone.utc),
            status=status,
            stop_reason=stop_reason,
            events_ref=events_ref,
            final_state_ref=final_state_ref,
            sealed_artifact_ref=sealed_ref,
            sealed_artifact_hash=hashlib.sha256(sealed_bytes).hexdigest(),
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


@dataclass(frozen=True)
class DeepSeekSmokeOutcome:
    """Non-persistent result of the bounded two-request real-smoke loop."""

    run: Run
    physical_attempts: int
    file_reads: int
    final_response_observed: bool


def run_deepseek_add_smoke(
    runtime: CapturedRuntime,
    provider: CapturedProvider,
    *,
    model: str,
) -> DeepSeekSmokeOutcome:
    """Bounded add-task loop: model command → observed tool → model.

    It is deliberately task-specific, synchronous, and capped at five physical
    attempts.  Invalid model output stops truthfully; no hidden retry exists.
    """
    system_prompt = (
        "You are operating through a strict command protocol.\n"
        "Reply with exactly ONE command per turn. Do not explain. Do not use Markdown code fences. "
        "Do not add text before or after the command.\n\n"
        "Allowed commands:\n\n"
        "READ target.py\n\n"
        "WRITE target.py\n"
        "<complete file contents>\n\n"
        "TEST\n\n"
        "FINAL\n\n"
        "Before editing an unseen target.py, first use READ target.py. To modify the file, you MUST "
        "use WRITE. Returning Python code without WRITE does not modify the workspace."
    )
    system_ref = runtime.public_context_ref(
        system_prompt,
        source_id="acr_runtime_config",
        trajectory_key="deepseek_command_protocol_v1",
        locator="/system-prompt",
    )
    task_ref = runtime.public_context_ref(
        runtime.task.public_instruction,
        source_id="acr_public_task",
        trajectory_key=runtime.task.task_id,
        locator="/public-instruction",
    )
    messages = [
        ConversationMessage(
            "system",
            system_prompt,
            origin_event_id="public:system:deepseek_command_protocol_v1",
            provenance_ref=system_ref,
        ),
        ConversationMessage(
            "user",
            runtime.task.public_instruction,
            origin_event_id=f"public-task:{runtime.task.task_id}:instruction",
            provenance_ref=task_ref,
        ),
    ]
    attempts = reads = 0
    changed = final_response_observed = False
    for step in range(5):
        body = serialize_deepseek_chat_request(
            model=model, messages=[message.wire() for message in messages]
        )
        request_id = f"add-loop-{step}"
        runtime.send_request(
            provider, body, request_id,
            runtime.context_blocks(f"request:attempt:{runtime.run_id}:{attempts}", messages),
        )
        attempts += 1
        attempt = runtime.last_attempt
        if attempt is None or attempt.raw_response_ref is None:
            break
        from acr.store import load_blob

        response = extract_deepseek_message_content(load_blob(runtime.data_root, attempt.raw_response_ref.blob_hash))
        if response is None:
            break
        final_response_observed = True
        if runtime.last_terminal_event_id is None or runtime.last_terminal_seq is None:
            break
        response_ref = attempt.raw_response_ref.model_copy(
            update={
                "labels": [
                    InformationLabel(
                        scope="runtime",
                        run_id=runtime.run_id,
                        available_seq=runtime.last_terminal_seq,
                    )
                ]
            }
        )
        messages.append(
            ConversationMessage(
                "assistant",
                response,
                origin_event_id=runtime.last_terminal_event_id,
                provenance_ref=response_ref,
            )
        )
        command = response.strip()
        if command == "READ target.py":
            read = runtime.tools.read_file("target.py")
            reads += 1
            messages.append(
                ConversationMessage(
                    "user",
                    f"TOOL RESULT read_file target.py:\n{read.text}",
                    origin_event_id=read.binding.read_event_id,
                    tool_call_id=read.tool_call_id,
                    file_binding=read.binding,
                    provenance_ref=read.body_ref,
                )
            )
        elif command.startswith("WRITE target.py\n"):
            write = runtime.tools.write_file("target.py", command.split("\n", 1)[1])
            changed = True
            messages.append(
                ConversationMessage(
                    "user",
                    "TOOL RESULT write_file completed",
                    origin_event_id=write.finish_event_id,
                    tool_call_id=write.tool_call_id,
                    provenance_ref=write.body_ref,
                )
            )
        elif command == "TEST":
            test = runtime.tools.run_test()
            messages.append(
                ConversationMessage(
                    "user",
                    f"TOOL RESULT run_test: {json.dumps(test.value, sort_keys=True)}",
                    origin_event_id=test.finish_event_id,
                    tool_call_id=test.tool_call_id,
                    provenance_ref=test.body_ref,
                )
            )
        elif command == "FINAL":
            break
        else:
            break
    run = runtime.seal(
        status="completed" if final_response_observed and changed else "task_failed",
        stop_reason=None if final_response_observed and changed else "agent_did_not_modify_workspace",
    )
    return DeepSeekSmokeOutcome(run, attempts, reads, final_response_observed)
