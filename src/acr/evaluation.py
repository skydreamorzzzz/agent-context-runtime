"""Independent, sealed-run-only evaluator for the private add-task spec."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from acr.contracts import EvaluationResult, EvidenceRef, Fact, Run
from acr.store import ingest_evaluator_bytes, load_blob, persist_evaluation_json


class EvaluationHandoffRejected(ValueError):
    """Raised before any private evaluator input may be opened."""


def require_sealed_run(sealed_run: Run) -> None:
    if sealed_run.sealed_artifact_ref is None or sealed_run.sealed_artifact_hash is None:
        raise EvaluationHandoffRejected("evaluation requires a sealed run")


class LocalAddEvaluator:
    """Fixed private evaluator; it never enters the runtime/provider boundary."""

    def __init__(
        self,
        *,
        data_root: Path,
        sealed_workspace: Path | None = None,
        code_revision: str | None = None,
    ) -> None:
        self._data_root = data_root
        self._sealed_workspace = sealed_workspace
        # Tests may inject a synthetic revision.  Real evaluator invocations use
        # the clean repository revision captured below, rather than claiming a
        # post-hoc HEAD for dirty execution.
        self._code_revision = code_revision

    def evaluate(self, sealed_run: Run, private_spec_ref: str) -> EvaluationResult:
        require_sealed_run(sealed_run)
        code_revision = self._execution_code_revision()
        # The private spec is first opened only after both sealed checks.
        private_spec = Path(private_spec_ref)
        spec_bytes = private_spec.read_bytes()
        spec_hash = hashlib.sha256(spec_bytes).hexdigest()
        # The evaluator verifies the sealed workspace, then executes private
        # tests in an isolated copy.  Imports and test by-products must never
        # mutate the sealed artifact used as the submission identity.
        with tempfile.TemporaryDirectory(prefix="acr-evaluator-") as temporary:
            execution_workspace = Path(temporary) / "workspace"
            self._materialize_sealed_workspace(sealed_run, execution_workspace)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "acr.evaluation_worker",
                    "--workspace",
                    str(execution_workspace),
                    "--spec",
                    str(private_spec),
                ],
                capture_output=True,
                check=False,
                text=False,
            )
        raw = completed.stdout if completed.returncode == 0 else json.dumps(
            {"status": "infra_error", "error_type": "evaluator_worker_failed"}, sort_keys=True
        ).encode()
        raw_ref = ingest_evaluator_bytes(raw, self._data_root, sealed_run.id, "/evaluation/result")
        producer_ref = self._persist_producer(sealed_run.id, spec_hash, code_revision)
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

    def _materialize_sealed_workspace(self, sealed_run: Run, destination: Path) -> None:
        """Reconstruct the submitted regular files from persisted blobs only."""
        assert sealed_run.sealed_artifact_ref is not None
        try:
            raw = load_blob(self._data_root, sealed_run.sealed_artifact_ref.blob_hash)
            if hashlib.sha256(raw).hexdigest() != sealed_run.sealed_artifact_hash:
                raise ValueError("sealed artifact hash mismatch")
            artifact = json.loads(raw)
            files = artifact["files"]
            if not isinstance(files, list):
                raise TypeError("sealed artifact files malformed")
            destination.mkdir(parents=True)
            for item in files:
                path = item["path"]
                ref = EvidenceRef.model_validate(item["body_ref"])
                if not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts:
                    raise ValueError("sealed artifact path invalid")
                body = load_blob(self._data_root, ref.blob_hash)
                if hashlib.sha256(body).hexdigest() != item["sha256"]:
                    raise ValueError("sealed file hash mismatch")
                target = destination / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise EvaluationHandoffRejected("sealed artifact cannot be materialized") from error

    def _execution_code_revision(self) -> str:
        if self._code_revision is not None:
            return self._code_revision
        try:
            if subprocess.check_output(["git", "status", "--porcelain"], text=True):
                raise EvaluationHandoffRejected("evaluator execution requires a clean working tree")
            revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        except (OSError, subprocess.CalledProcessError) as error:
            raise EvaluationHandoffRejected("evaluator code revision is unavailable") from error
        if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
            raise EvaluationHandoffRejected("evaluator code revision is malformed")
        return revision

    def _persist_producer(self, run_id: str, spec_hash: str, code_revision: str) -> EvidenceRef:
        manifest = {
            "producer_kind": "acr_local_add_evaluator",
            "schema_version": "1.0",
            "evaluator_version": "local_add_evaluator_v1",
            "code_revision": code_revision,
            "private_spec_sha256": spec_hash,
        }
        raw = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
        ref = ingest_evaluator_bytes(raw, self._data_root, run_id, "/evaluation/producer-manifest")
        persist_evaluation_json(self._data_root, run_id, "producer_manifest.json", manifest)
        persist_evaluation_json(self._data_root, run_id, "producer_ref.json", ref)
        return ref
