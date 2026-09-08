"""The deliberately small M2 tool boundary: complete ``read_file`` only."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from acr.contracts import EvidenceRef, FileBinding, InformationLabel
from acr.execution import IsolationUnavailable, run_isolated_python
from acr.state import read_workspace_file
from acr.store import ingest_runtime_bytes

_PUBLIC_ADD_TEST = r"""
import importlib.util
import json

try:
    spec = importlib.util.spec_from_file_location("submitted_target", "/workspace/target.py")
    if spec is None or spec.loader is None:
        raise ImportError("submitted target cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    passed = callable(module.add) and module.add(1, 2) == 3 and module.add(-1, 1) == 0
    result = {"status": "completed", "passed": bool(passed)}
except BaseException as error:
    result = {"status": "submission_error", "error_type": type(error).__name__}
print("ACR_RESULT=" + json.dumps(result, sort_keys=True))
"""
PUBLIC_TEST_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class FileReadResult:
    tool_call_id: str
    binding: FileBinding
    body_ref: EvidenceRef
    text: str


@dataclass(frozen=True)
class ToolExecutionResult:
    """One completed non-read tool occurrence and its exact result evidence."""

    tool_call_id: str
    finish_event_id: str
    available_seq: int
    body_ref: EvidenceRef
    value: dict[str, object]


class RuntimeTools:
    """The fixed add-task tool boundary; no shell or generic tool framework."""

    def __init__(
        self,
        workspace: Path,
        data_root: Path,
        run_id: str,
        record: Callable[[str, str | None, dict[str, object], bool], tuple[str, int]],
    ) -> None:
        self._workspace = workspace
        self._data_root = data_root
        self._run_id = run_id
        self._record = record
        self._counter = 0
        self._bindings: list[FileBinding] = []

    @property
    def bindings(self) -> list[FileBinding]:
        return list(self._bindings)

    def read_file(self, repo_relative_path: str) -> FileReadResult:
        """Capture invocation, actual bytes, binding, and terminal tool event."""

        tool_call_id = f"tool:{self._run_id}:{self._counter}"
        self._counter += 1
        self._record(
            "tool_start",
            tool_call_id,
            {"tool": "read_file", "path": repo_relative_path, "read_mode": "utf-8-full"},
            False,
        )
        try:
            resolved, raw = read_workspace_file(self._workspace, repo_relative_path)
            body_ref = ingest_runtime_bytes(
                raw,
                self._data_root,
                self._run_id,
                f"/tools/{tool_call_id}/body",
            )
            finish_id, available_seq = self._record(
                "tool_finish",
                tool_call_id,
                {
                    "tool": "read_file",
                    "path": repo_relative_path,
                    "resolved_path": resolved.relative_to(self._workspace.resolve()).as_posix(),
                    "body_ref": body_ref.model_dump(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "encoding": "utf-8",
                    "complete": True,
                },
                True,
            )
        except Exception as error:
            self._record(
                "tool_finish",
                tool_call_id,
                {
                    "tool": "read_file",
                    "path": repo_relative_path,
                    "error": type(error).__name__,
                    "complete": False,
                },
                True,
            )
            raise
        visible_body_ref = body_ref.model_copy(
            update={
                "labels": [
                    InformationLabel(
                        scope="runtime", run_id=self._run_id, available_seq=available_seq
                    )
                ]
            }
        )
        binding = FileBinding(
            repo_relative_path=repo_relative_path,
            file_sha256=hashlib.sha256(raw).hexdigest(),
            encoding="utf-8",
            read_event_id=finish_id,
            observed_seq=available_seq,
            complete=True,
        )
        self._bindings.append(binding)
        return FileReadResult(
            tool_call_id=tool_call_id,
            binding=binding,
            body_ref=visible_body_ref,
            text=raw.decode("utf-8"),
        )

    def write_file(self, repo_relative_path: str, text: str) -> ToolExecutionResult:
        """Write one UTF-8 regular workspace file with start/finish evidence."""

        tool_call_id = f"tool:{self._run_id}:{self._counter}"
        self._counter += 1
        self._record("tool_start", tool_call_id, {"tool": "write_file", "path": repo_relative_path}, False)
        try:
            resolved, _ = read_workspace_file(self._workspace, repo_relative_path)
            raw = text.encode("utf-8")
            resolved.write_bytes(raw)
            body_ref = ingest_runtime_bytes(raw, self._data_root, self._run_id, f"/tools/{tool_call_id}/body")
            finish_id, available_seq = self._record(
                "tool_finish", tool_call_id,
                {"tool": "write_file", "path": repo_relative_path, "body_ref": body_ref.model_dump(), "sha256": hashlib.sha256(raw).hexdigest(), "complete": True},
                True,
            )
        except Exception as error:
            self._record("tool_finish", tool_call_id, {"tool": "write_file", "path": repo_relative_path, "error": type(error).__name__, "complete": False}, True)
            raise
        visible_body_ref = body_ref.model_copy(
            update={
                "labels": [
                    InformationLabel(
                        scope="runtime", run_id=self._run_id, available_seq=available_seq
                    )
                ]
            }
        )
        return ToolExecutionResult(
            tool_call_id=tool_call_id,
            finish_event_id=finish_id,
            available_seq=available_seq,
            body_ref=visible_body_ref,
            value={"status": "completed", "path": repo_relative_path},
        )

    def run_test(self) -> ToolExecutionResult:
        """Run the public add check inside the fixed Linux isolation boundary."""

        tool_call_id = f"tool:{self._run_id}:{self._counter}"
        self._counter += 1
        self._record("tool_start", tool_call_id, {"tool": "run_test", "command": "public-add-check"}, False)
        try:
            execution = run_isolated_python(
                self._workspace,
                _PUBLIC_ADD_TEST,
                timeout_seconds=PUBLIC_TEST_TIMEOUT_SECONDS,
            )
            worker_result = _worker_result(execution.stdout)
            status = "timeout" if execution.status == "timeout" else "completed"
            if execution.status != "timeout" and worker_result is None:
                status = "submission_error"
            raw_value: dict[str, object] = {
                "status": status,
                "returncode": execution.returncode,
                "stdout": execution.stdout.decode(errors="replace"),
                "stderr": execution.stderr.decode(errors="replace"),
                "stdout_truncated": execution.stdout_truncated,
                "stderr_truncated": execution.stderr_truncated,
                "result": worker_result,
            }
        except IsolationUnavailable as error:
            raw_value = {
                "status": "infra_error",
                "error_type": type(error).__name__,
                "stdout": "",
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
                "result": None,
            }
        raw = json.dumps(raw_value, sort_keys=True).encode()
        body_ref = ingest_runtime_bytes(raw, self._data_root, self._run_id, f"/tools/{tool_call_id}/body")
        finish_id, available_seq = self._record(
            "tool_finish",
            tool_call_id,
            {
                "tool": "run_test",
                "body_ref": body_ref.model_dump(),
                "status": raw_value["status"],
                "returncode": raw_value.get("returncode"),
                "complete": True,
            },
            True,
        )
        visible_body_ref = body_ref.model_copy(
            update={
                "labels": [
                    InformationLabel(
                        scope="runtime", run_id=self._run_id, available_seq=available_seq
                    )
                ]
            }
        )
        return ToolExecutionResult(
            tool_call_id=tool_call_id,
            finish_event_id=finish_id,
            available_seq=available_seq,
            body_ref=visible_body_ref,
            value=json.loads(raw),
        )


def _worker_result(stdout: bytes) -> dict[str, object] | None:
    for line in reversed(stdout.decode(errors="replace").splitlines()):
        if line.startswith("ACR_RESULT="):
            try:
                result = json.loads(line.removeprefix("ACR_RESULT="))
            except json.JSONDecodeError:
                return None
            return result if isinstance(result, dict) else None
    return None


def tool_result_payload(result: FileReadResult) -> bytes:
    """Serialize a result only from the actual body binding, never caller text."""

    return json.dumps(
        {
            "tool_call_id": result.tool_call_id,
            "body_ref": result.body_ref.model_dump(),
            "file_sha256": result.binding.file_sha256,
        },
        sort_keys=True,
    ).encode()
