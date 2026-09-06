"""Fail-closed validation of the small execution-config boundary.

This module validates only the evidence/configuration fields required before a
future real run may start. It does not load files, select providers, or price
usage.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

REQUIRED_RUN_CONFIG_FIELDS = (
    "provider",
    "model",
    "task_manifest",
    "image_digest",
    "budget",
    "price_snapshot",
)


class RunConfigValidationError(ValueError):
    """Raised when a future executable run lacks frozen required inputs."""


def validate_run_config(config: Mapping[str, Any]) -> None:
    """Reject a future executable run when required config/evidence is absent.

    A non-empty ``price_snapshot`` is an evidence reference, not a claim that
    every provider rate is known. Price availability remains an explicit later
    accounting outcome; an absent reference is rejected as missing evidence.
    """

    missing = [field for field in REQUIRED_RUN_CONFIG_FIELDS if _is_missing(config.get(field))]
    if missing:
        if missing == ["price_snapshot"]:
            raise RunConfigValidationError("missing price evidence: price_snapshot")
        raise RunConfigValidationError(f"missing required run configuration: {', '.join(missing)}")


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
