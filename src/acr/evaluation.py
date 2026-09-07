"""Independent, sealed-run-only evaluator for the private add-task spec."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from acr.contracts import EvaluationResult, EvidenceRef, Fact, Run
from acr.state import initial_tree_manifest
from acr.store import ingest_evaluator_bytes, persist_evaluation_json


class EvaluationHandoffRejected(ValueError):
    """Raised before any private evaluator input may be opened."""


def require_sealed_run(sealed_run: Run) -> None:
    if sealed_run.sealed_artifact_ref is None or sealed_run.sealed_artifact_hash is None:
        raise EvaluationHandoffRejected("evaluation requires a sealed run")


class LocalAddEvaluator:
    """Fixed private evaluator; it never enters the runtime/provider boundary."""

    def __init__(self, *, data_root: Path, sealed_workspace: Path) -> None:
        self._data_root = data_root
        self._sealed_workspace = sealed_workspace

    def evaluate(self, sealed_run: Run, private_spec_ref: str) -> EvaluationResult:
        require_sealed_run(sealed_run)
        tree, _ = initial_tree_manifest(self._sealed_workspace)
        tree_hash = hashlib.sha256(json.dumps(tree, sort_keys=True).encode()).hexdigest()
        if tree_hash != sealed_run.sealed_artifact_hash:
            raise EvaluationHandoffRejected("sealed workspace does not match sealed artifact")
        # The private spec is first opened only after both sealed checks.
        private_spec = Path(private_spec_ref)
        spec_bytes = private_spec.read_bytes()
        spec_hash = hashlib.sha256(spec_bytes).hexdigest()
        completed = subprocess.run(
            [sys.executable, "-m", "acr.evaluation_worker", "--workspace", str(self._sealed_workspace), "--spec", str(private_spec)],
            capture_output=True,
            check=False,
            text=False,
        )
        raw = completed.stdout if completed.returncode == 0 else json.dumps(
            {"status": "infra_error", "error_type": "evaluator_worker_failed"}, sort_keys=True
        ).encode()
        raw_ref = ingest_evaluator_bytes(raw, self._data_root, sealed_run.id, "/evaluation/result")
        producer_ref = self._persist_producer(sealed_run.id, spec_hash)
        try:
            record = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            record = {"status": "infra_error"}
        if record.get("status") != "completed":
            unknown = Fact[int](status="unknown", reason="evaluator_infra_error")
            result = EvaluationResult(
                kind="evaluation_result", id=f"evaluation:{sealed_run.id}", producer_ref=producer_ref,
                run_id=sealed_run.id, submitted_artifact_hash=sealed_run.sealed_artifact_hash,
                evaluator_revision="local_add_evaluator_v1", status="infra_error",
                patch_valid=Fact[bool](status="unknown", reason="evaluator_infra_error"),
                tests_executed=unknown, passed=unknown.model_copy(), failed=unknown.model_copy(),
                resolved=Fact[bool](status="unknown", reason="evaluator_infra_error"), raw_result_ref=raw_ref,
            )
        else:
            result = EvaluationResult(
                kind="evaluation_result", id=f"evaluation:{sealed_run.id}", producer_ref=producer_ref,
                run_id=sealed_run.id, submitted_artifact_hash=sealed_run.sealed_artifact_hash,
                evaluator_revision="local_add_evaluator_v1", status="completed",
                patch_valid=Fact[bool](value=record["patch_valid"], status="observed", refs=[raw_ref]),
                tests_executed=Fact[int](value=record["tests_executed"], status="observed", refs=[raw_ref]),
                passed=Fact[int](value=record["passed"], status="observed", refs=[raw_ref]),
                failed=Fact[int](value=record["failed"], status="observed", refs=[raw_ref]),
                resolved=Fact[bool](value=record["resolved"], status="observed", refs=[raw_ref]), raw_result_ref=raw_ref,
            )
        persist_evaluation_json(self._data_root, sealed_run.id, "evaluation_result.json", result)
        return result

    def _persist_producer(self, run_id: str, spec_hash: str) -> EvidenceRef:
        manifest = {"producer_kind": "acr_local_add_evaluator", "schema_version": "1.0", "evaluator_version": "local_add_evaluator_v1", "private_spec_sha256": spec_hash}
        raw = json.dumps(manifest, sort_keys=True).encode()
        ref = ingest_evaluator_bytes(raw, self._data_root, run_id, "/evaluation/producer-manifest")
        persist_evaluation_json(self._data_root, run_id, "producer_manifest.json", manifest)
        persist_evaluation_json(self._data_root, run_id, "producer_ref.json", ref)
        return ref
