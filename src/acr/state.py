"""Narrow workspace-state evidence for the synchronous M2 runtime."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from acr.contracts import EvidenceRef, FileBinding, FileComparison, InformationLabel
from acr.store import ingest_runtime_bytes, load_blob


class WorkspaceViolation(ValueError):
    """Raised when a runtime path cannot be proven to stay in its workspace."""


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def verified_workspace(workspace: Path, *, forbidden_roots: tuple[Path, ...] = ()) -> Path:
    """Resolve and verify a workspace without permitting evaluator/data-root overlap."""

    root = workspace.resolve(strict=True)
    if not root.is_dir():
        raise WorkspaceViolation("workspace is not a directory")
    for forbidden in forbidden_roots:
        candidate = forbidden.resolve(strict=False)
        if _inside(candidate, root) or _inside(root, candidate):
            raise WorkspaceViolation("runtime workspace overlaps a protected root")
    return root


def initial_tree_manifest(workspace: Path) -> tuple[dict[str, object], str]:
    """Return a deterministic, conservative manifest of regular workspace files.

    This deliberately rejects symlinks rather than trying to attribute their
    targets.  It verifies an initial tree only; it does not claim checkpoint or
    full dynamic-state recovery.
    """

    root = verified_workspace(workspace)
    files: list[dict[str, object]] = []
    for current, directories, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(directories)
        names.sort()
        for dirname in directories:
            if (current_path / dirname).is_symlink():
                raise WorkspaceViolation("workspace contains a symlink")
        for name in names:
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise WorkspaceViolation("workspace contains a non-regular file")
            raw = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "mode": path.stat().st_mode & 0o777,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
    manifest: dict[str, object] = {"files": files}
    return manifest, tree_manifest_hash(manifest)


def tree_manifest_hash(manifest: dict[str, object]) -> str:
    """Hash repository-relative state, never the executor's directory name."""

    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_workspace_file(workspace: Path, repo_relative_path: str) -> tuple[Path, bytes]:
    """Read actual bytes from one complete UTF-8 regular file inside workspace."""

    root = verified_workspace(workspace)
    requested = Path(repo_relative_path)
    if requested.is_absolute() or ".." in requested.parts or not repo_relative_path:
        raise WorkspaceViolation("file path must be a non-empty workspace-relative path")
    lexical = root / requested
    if lexical.is_symlink():
        raise WorkspaceViolation("symlink reads are unsupported")
    resolved = lexical.resolve(strict=True)
    if not _inside(resolved, root) or not resolved.is_file() or resolved.is_symlink():
        raise WorkspaceViolation("file path escapes workspace or is not a regular file")
    raw = resolved.read_bytes()
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WorkspaceViolation("only complete UTF-8 file reads are supported") from error
    return resolved, raw


def compare_file(
    workspace: Path,
    binding: FileBinding,
    binding_ref: EvidenceRef,
    *,
    data_root: Path,
    run_id: str,
    checked_seq: int,
) -> FileComparison:
    """Re-read one bound file conservatively at a synchronous decision boundary."""

    binding_labels = [
        label
        for label in binding_ref.labels
        if label.scope == "runtime" and label.run_id == run_id and not label.taints
    ]
    if (
        not binding.complete
        or binding.range != "full"
        or binding.encoding != "utf-8"
        or Path(binding.repo_relative_path).as_posix() != binding.repo_relative_path
        or binding_ref.source_id != "acr_runtime"
        or binding_ref.trajectory_key != run_id
        or binding_ref.blob_hash != binding.file_sha256
        or len(binding_labels) != 1
        or binding_labels[0].available_seq != binding.observed_seq
        or checked_seq < binding.observed_seq
    ):
        return FileComparison(
            binding_ref=binding_ref,
            checked_seq=checked_seq,
            status="unknown",
            reason="historical_binding_unverified",
        )
    try:
        historical = load_blob(data_root, binding_ref.blob_hash)
        if hashlib.sha256(historical).hexdigest() != binding.file_sha256:
            raise ValueError("historical binding bytes do not match")
        _, current = read_workspace_file(workspace, binding.repo_relative_path)
    except (FileNotFoundError, OSError, UnicodeError, ValueError, WorkspaceViolation):
        return FileComparison(
            binding_ref=binding_ref,
            checked_seq=checked_seq,
            status="unknown",
            reason="current_file_unavailable_or_unsafe",
        )
    current_hash = hashlib.sha256(current).hexdigest()
    current_ref = ingest_runtime_bytes(
        current,
        data_root,
        run_id,
        f"/state-checks/{checked_seq}/{binding.repo_relative_path}",
    ).model_copy(
        update={
            "labels": [
                InformationLabel(scope="runtime", run_id=run_id, available_seq=checked_seq)
            ]
        }
    )
    return FileComparison(
        binding_ref=binding_ref,
        current_file_sha256=current_hash,
        current_file_ref=current_ref,
        checked_seq=checked_seq,
        status="same" if current_hash == binding.file_sha256 else "changed",
    )
