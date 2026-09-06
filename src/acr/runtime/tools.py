"""The deliberately small M2 tool boundary: complete ``read_file`` only."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from acr.contracts import EvidenceRef, FileBinding
from acr.state import read_workspace_file
from acr.store import ingest_runtime_bytes


@dataclass(frozen=True)
class FileReadResult:
    tool_call_id: str
    binding: FileBinding
    body_ref: EvidenceRef
    text: str


class RuntimeTools:
    """Serial read-file instrumentation; no shell or generic tool framework."""

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
            body_ref=body_ref,
            text=raw.decode("utf-8"),
        )


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
