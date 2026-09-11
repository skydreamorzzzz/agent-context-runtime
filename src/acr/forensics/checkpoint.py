"""Production captured-repository-state checkpoint materialization."""

from __future__ import annotations

import errno
import os
import stat
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from acr.contracts import EvidenceRef, Fact
from acr.forensics.config import validate_repo_relative_path
from acr.forensics.store import ForensicsEvidenceStore, canonical_json_bytes
from acr.forensics_contracts import (
    CAPTURE_POLICY_VERSION,
    CapturedPathState,
    CaptureScopeEntry,
    OrderingEvidence,
    WorkspaceCheckpoint,
    canonical_captured_state_manifest_bytes,
)

_REGULAR_GIT_MODES = {"100644", "100755"}
_SENSITIVE_EXACT_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_ecdsa",
    "id_rsa",
}
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_SENSITIVE_CONTENT_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"github_pat_",
    b"ghp_",
    b"sk-ant-",
)
_EXCLUDED_PREFIXES = (".claude/", ".git/", ".acr/")


class CheckpointCaptureError(RuntimeError):
    """A repository state could not be safely captured."""


@dataclass(frozen=True)
class _ReadResult:
    state: str
    content: bytes | None = None
    executable: bool | None = None
    reason: str | None = None


def _run_git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise CheckpointCaptureError("Git executable is unavailable") from error
    if check and result.returncode != 0:
        raise CheckpointCaptureError("Git repository observation failed")
    return result


def _decode_git_path(value: bytes) -> str:
    try:
        decoded = value.decode("utf-8")
        return validate_repo_relative_path(decoded)
    except (UnicodeDecodeError, ValueError) as error:
        raise CheckpointCaptureError("Git reported an unsupported repository path") from error


def _tracked_index(repo_root: Path) -> tuple[dict[str, str], dict[str, str]]:
    output = _run_git(repo_root, "ls-files", "--stage", "-z").stdout
    modes: dict[str, str] = {}
    unsupported: dict[str, str] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            raw_mode, _object_hash, raw_stage = header.split(b" ", 2)
            mode = raw_mode.decode("ascii")
            stage = raw_stage.decode("ascii")
        except (ValueError, UnicodeDecodeError) as error:
            raise CheckpointCaptureError("Git index output was malformed") from error
        path = _decode_git_path(raw_path)
        if stage != "0" or path in modes or path in unsupported:
            unsupported[path] = "unmerged_or_duplicate_git_index_entry"
            modes.pop(path, None)
        elif mode in _REGULAR_GIT_MODES:
            modes[path] = mode
        else:
            unsupported[path] = f"unsupported_git_index_mode_{mode}"
    return modes, unsupported


def _is_sensitive(path: str) -> bool:
    parts = PurePosixPath(path).parts
    lowered = tuple(part.lower() for part in parts)
    name = lowered[-1]
    return (
        path.startswith(_EXCLUDED_PREFIXES)
        or name in _SENSITIVE_EXACT_NAMES
        or name.startswith(".env.")
        or name.endswith(_SENSITIVE_SUFFIXES)
        or "secrets" in lowered
    )


def _secure_read(repo_root: Path, relative_path: str, max_bytes: int) -> _ReadResult:
    parts = PurePosixPath(validate_repo_relative_path(relative_path)).parts
    flags_directory = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags_file = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        try:
            current = os.open(repo_root, flags_directory)
            descriptors.append(current)
            for part in parts[:-1]:
                current = os.open(part, flags_directory, dir_fd=current)
                descriptors.append(current)
            descriptor = os.open(parts[-1], flags_file, dir_fd=current)
            descriptors.append(descriptor)
        except FileNotFoundError:
            return _ReadResult(state="deleted")
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                return _ReadResult(
                    state="unsupported", reason="symlink_or_non_directory_component"
                )
            raise CheckpointCaptureError("captured path could not be safely opened") from error
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            return _ReadResult(state="unsupported", reason="unsupported_non_regular_file")
        if before.st_nlink > 1:
            return _ReadResult(state="unsupported", reason="unsupported_hardlinked_file")
        if before.st_size > max_bytes:
            return _ReadResult(state="unsupported", reason="file_exceeds_capture_size_cap")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > max_bytes:
                return _ReadResult(state="unsupported", reason="file_exceeds_capture_size_cap")
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after:
            return _ReadResult(state="unsupported", reason="file_changed_during_capture")
        return _ReadResult(
            state="present",
            content=b"".join(chunks),
            executable=bool(before.st_mode & 0o111),
        )
    finally:
        for item in reversed(descriptors):
            os.close(item)


def _is_ignored(repo_root: Path, path: str) -> bool:
    result = _run_git(repo_root, "check-ignore", "--quiet", "--", path, check=False)
    if result.returncode not in {0, 1}:
        raise CheckpointCaptureError("Git ignore observation failed")
    return result.returncode == 0


def _gap(area: str, path: str | None, disposition: str, reason: str) -> dict[str, str | None]:
    return {"area": area, "path": path, "disposition": disposition, "reason": reason}


def capture_workspace_checkpoint(
    *,
    store: ForensicsEvidenceStore,
    repo_root: Path,
    session_metadata: dict[str, Any],
    trigger_event_ref: EvidenceRef,
    trigger_operation_id: str,
) -> tuple[WorkspaceCheckpoint, EvidenceRef]:
    """Synchronously capture the verifier's pre-execution repository state."""

    repo_root = repo_root.resolve()
    top_level = _run_git(repo_root, "rev-parse", "--show-toplevel").stdout.decode().strip()
    if Path(top_level).resolve() != repo_root:
        raise CheckpointCaptureError("configured repository root does not match Git top level")
    git_base = _run_git(repo_root, "rev-parse", "--verify", "HEAD^{commit}").stdout.decode().strip()
    if not git_base:
        raise CheckpointCaptureError("repository has no observable Git base commit")

    tracked, unsupported_index = _tracked_index(repo_root)
    selected = session_metadata["selected_untracked_paths"]
    if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
        raise CheckpointCaptureError("selected untracked path configuration is malformed")
    path_kinds = {path: "tracked" for path in tracked}
    gaps: list[dict[str, str | None]] = []
    for path, reason in unsupported_index.items():
        gaps.append(_gap("tracked_regular_files", path, "unsupported", reason))
    for path in selected:
        try:
            validate_repo_relative_path(path)
        except ValueError as error:
            raise CheckpointCaptureError("unsafe selected untracked path") from error
        if path not in path_kinds:
            if _is_ignored(repo_root, path):
                gaps.append(
                    _gap("selected_untracked_files", path, "excluded_by_policy", "git_ignored")
                )
            else:
                path_kinds[path] = "selected_untracked"

    try:
        relative_data_root = store.data_root.relative_to(repo_root).as_posix()
    except ValueError:
        relative_data_root = None

    entries: list[dict[str, Any]] = []
    content_refs: list[EvidenceRef] = []
    producer_ref = EvidenceRef.model_validate(session_metadata["producer_ref"])
    max_blob_bytes = session_metadata["max_blob_bytes"]
    if not isinstance(max_blob_bytes, int) or max_blob_bytes < 1:
        raise CheckpointCaptureError("capture size policy is malformed")
    for path in sorted(path_kinds):
        area = (
            "tracked_regular_files"
            if path_kinds[path] == "tracked"
            else "selected_untracked_files"
        )
        if _is_sensitive(path) or (
            relative_data_root is not None
            and (path == relative_data_root or path.startswith(f"{relative_data_root}/"))
        ):
            gaps.append(_gap(area, path, "excluded_by_policy", "sensitive_or_evidence_path"))
            continue
        result = _secure_read(repo_root, path, max_blob_bytes)
        if result.state == "unsupported":
            gaps.append(_gap(area, path, "unsupported", result.reason or "unsupported"))
            continue
        content_ref = None
        if result.state == "present":
            assert result.content is not None and result.executable is not None
            if any(marker in result.content for marker in _SENSITIVE_CONTENT_MARKERS):
                gaps.append(
                    _gap(area, path, "excluded_by_policy", "sensitive_content_default_deny")
                )
                continue
            content_ref = store.ref_for_bytes(
                result.content,
                source_id="acr_forensics_captured_file",
                locator=f"/captured-files/{path}",
            )
            content_refs.append(content_ref)
        entries.append(
            {
                "content_ref": content_ref,
                "executable": result.executable,
                "path_kind": path_kinds[path],
                "repo_relative_path": path,
                "state": result.state,
            }
        )

    provisional_paths = [
        CapturedPathState(state_ref=producer_ref, **entry) for entry in entries
    ]
    manifest_bytes = canonical_captured_state_manifest_bytes(git_base, provisional_paths)
    manifest_ref = store.persist_manifest(manifest_bytes)
    capture_observation = {
        "capture_gaps": sorted(
            gaps,
            key=lambda item: (str(item["area"]), str(item["path"]), str(item["reason"])),
        ),
        "git_base": git_base,
        "manifest_hash": manifest_ref.blob_hash,
        "path_count": len(entries),
        "schema": "acr.repository-capture-observation/0.1",
    }
    capture_ref = store.ref_for_bytes(
        canonical_json_bytes(capture_observation),
        source_id="acr_forensics_capture_observation",
        locator=f"/captures/{trigger_operation_id}",
    )
    captured_paths = [
        CapturedPathState(state_ref=capture_ref, **entry) for entry in entries
    ]
    if canonical_captured_state_manifest_bytes(git_base, captured_paths) != manifest_bytes:
        raise CheckpointCaptureError("captured-state canonicalization changed during materialization")

    capture_scope = [
        CaptureScopeEntry(
            area="tracked_regular_files",
            captured=Fact(value=True, status="observed", refs=[capture_ref]),
            disposition="included",
        ),
        CaptureScopeEntry(
            area="selected_untracked_files",
            captured=Fact(value=True, status="observed", refs=[capture_ref]),
            disposition="included",
        ),
    ]
    for gap in gaps:
        capture_scope.append(
            CaptureScopeEntry(
                area=gap["area"],
                repo_relative_path=gap["path"],
                captured=Fact(value=False, status="observed", refs=[capture_ref]),
                disposition=gap["disposition"],
                reason=gap["reason"],
            )
        )
    for area, disposition, reason in (
        ("ignored_files", "not_captured", "outside_v0.1_capture_scope"),
        ("environment", "not_captured", "privacy_boundary"),
        ("running_processes", "not_captured", "outside_v0.1_capture_scope"),
        ("database", "unsupported", "outside_v0.1_capture_scope"),
        ("network", "unsupported", "outside_v0.1_capture_scope"),
    ):
        capture_scope.append(
            CaptureScopeEntry(
                area=area,
                captured=Fact(value=False, status="observed", refs=[capture_ref]),
                disposition=disposition,
                reason=reason,
            )
        )

    checkpoint_id = f"cp-{uuid.uuid4().hex}"
    provenance_ref = store.persist_provenance(
        identifier=f"prov-{uuid.uuid4().hex}",
        producer_ref=producer_ref,
        output_object=checkpoint_id,
        input_refs=[capture_ref, manifest_ref, *content_refs],
        transform_name="capture_repository_state",
        config_ref=EvidenceRef.model_validate(session_metadata["config_ref"]),
    )
    checkpoint = WorkspaceCheckpoint(
        id=checkpoint_id,
        producer_ref=producer_ref,
        provenance_ref=provenance_ref,
        session_id=store.session_id,
        ordering=OrderingEvidence(
            sequence=Fact(
                value=store.reserve_sequence(),
                status="observed",
                refs=[trigger_event_ref],
            ),
            basis="locked_session_sequence_v1",
        ),
        timestamp=datetime.now(timezone.utc),
        git_base=Fact(value=git_base, status="observed", refs=[capture_ref]),
        captured_workspace_manifest_hash=manifest_ref.blob_hash,
        manifest_ref=manifest_ref,
        captured_paths=captured_paths,
        capture_scope=capture_scope,
        capture_completeness=Fact(value=False, status="observed", refs=[capture_ref]),
        trigger=Fact(
            value="pre_exact_configured_verifier",
            status="observed",
            refs=[trigger_event_ref],
        ),
        capture_policy_version=CAPTURE_POLICY_VERSION,
    )
    checkpoint_ref = store.persist_record("checkpoints", checkpoint)
    return checkpoint, checkpoint_ref
