"""Narrow workspace-state evidence for the synchronous M2 runtime."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


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
