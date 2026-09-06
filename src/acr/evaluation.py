"""Minimal evaluator-domain boundary; this module does not evaluate tasks."""

from __future__ import annotations

from acr.contracts import Run


class EvaluationHandoffRejected(ValueError):
    """Raised before any private evaluator input may be opened."""


def require_sealed_run(sealed_run: Run) -> None:
    """Reject an unsealed runtime record at the evaluator boundary.

    A future evaluator invokes this in its own process before loading a private
    spec.  No private path, bytes, or evaluator result crosses into runtime.
    """

    if sealed_run.sealed_artifact_ref is None or sealed_run.sealed_artifact_hash is None:
        raise EvaluationHandoffRejected("evaluation requires a sealed run")
