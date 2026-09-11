"""Small, fail-closed project configuration for F1 capture."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from pydantic import Field, field_validator

from acr.contracts import ContractModel

DEFAULT_CONFIG_PATH = ".acr.json"
DEFAULT_DATA_ROOT = ".acr/evidence"
DEFAULT_MAX_BLOB_BYTES = 5 * 1024 * 1024
_SAFE_VERIFIER = re.compile(r"^[A-Za-z0-9_./:@%+=,-]+(?: [A-Za-z0-9_./:@%+=,-]+)*$")


def validate_repo_relative_path(value: str) -> str:
    """Require one canonical POSIX path with no traversal or aliases."""

    if not value or "\\" in value or "\x00" in value:
        raise ValueError("repository paths must be non-empty canonical POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
        raise ValueError("repository paths must be canonical and repository-relative")
    return value


class ForensicsConfig(ContractModel):
    """The deliberately small v0.1 product configuration."""

    verifier: str
    selected_untracked_paths: list[str] = Field(default_factory=list)
    data_root: str = DEFAULT_DATA_ROOT
    max_blob_bytes: int = Field(default=DEFAULT_MAX_BLOB_BYTES, ge=1, le=100 * 1024 * 1024)

    @field_validator("verifier")
    @classmethod
    def require_standalone_exact_command(cls, value: str) -> str:
        if not _SAFE_VERIFIER.fullmatch(value):
            raise ValueError(
                "verifier must be one standalone command in the v0.1 safe argument subset"
            )
        return value

    @field_validator("selected_untracked_paths")
    @classmethod
    def require_safe_unique_selected_paths(cls, values: list[str]) -> list[str]:
        normalized = [validate_repo_relative_path(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("selected untracked paths must be unique")
        return sorted(normalized)

    @field_validator("data_root")
    @classmethod
    def require_data_root(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("data_root must be a non-empty path")
        return value


class ProjectForensicsConfig(ContractModel):
    forensics: ForensicsConfig


def load_project_config(config_path: Path) -> ForensicsConfig:
    try:
        value = json.loads(config_path.read_text())
    except FileNotFoundError:
        raise ValueError(f"configuration not found: {config_path}") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"configuration is not valid readable JSON: {config_path}") from error
    return ProjectForensicsConfig.model_validate(value).forensics
