"""Independent, sealed-run-only evaluator for the private add-task spec."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from acr.contracts import EvaluationResult, EvidenceRef, Fact, Run
from acr.evaluation_worker import SUBMISSION_WORKER_SOURCE
from acr.execution import IsolationUnavailable, run_isolated_python
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
        timeout_seconds: float = 2.0,
    ) -> None:
        self._data_root = data_root
        self._sealed_workspace = sealed_workspace
        # Tests may inject a synthetic revision.  Real evaluator invocations use
        # the clean repository revision captured below, rather than claiming a
        # post-hoc HEAD for dirty execution.
        self._code_revision = code_revision
        self._timeout_seconds = timeout_seconds

    def evaluate(self, sealed_run: Run, private_spec_ref: str) -> EvaluationResult:
        require_sealed_run(sealed_run)
        code_revision = self._execution_code_revision()
        evaluation_started_at = datetime.now(timezone.utc)
        # The private spec is first opened only after the sealed check and start
        # attestation.  Its expected values remain in this trusted process.
        private_spec = Path(private_spec_ref)
        spec_bytes = private_spec.read_bytes()
        spec_hash = hashlib.sha256(spec_bytes).hexdigest()
        try:
            spec = json.loads(spec_bytes)
            tests = spec["tests"]
            if not isinstance(tests, list) or any(
                not isinstance(case, dict) or "args" not in case or "expected" not in case
                for case in tests
            ):
                raise ValueError("private evaluator cases are malformed")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            record: dict[str, object] = {
                "status": "infra_error",
                "error_type": "private_spec_malformed",
            }
        else:
            record = self._execute_cases(sealed_run, tests)
        raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        raw_ref = ingest_evaluator_bytes(raw, self._data_root, sealed_run.id, "/evaluation/result")
        producer_ref = self._persist_producer(
            sealed_run.id,
            spec_hash,
            code_revision,
            evaluation_started_at,
        )
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

    def _execute_cases(self, sealed_run: Run, tests: list[dict[str, object]]) -> dict[str, object]:
        """Compare private expected values only after isolated submissions return."""

        passed = 0
        submission_errors = 0
        submission_timeouts = 0
        with tempfile.TemporaryDirectory(prefix="acr-evaluator-") as temporary:
            execution_workspace = Path(temporary) / "workspace"
            self._materialize_sealed_workspace(sealed_run, execution_workspace)
            for case in tests:
                request = json.dumps({"args": case["args"]}, separators=(",", ":")).encode()
                try:
                    execution = run_isolated_python(
                        execution_workspace,
                        SUBMISSION_WORKER_SOURCE,
                        stdin=request,
                        timeout_seconds=self._timeout_seconds,
                    )
                except IsolationUnavailable:
                    return {
                        "status": "infra_error",
                        "error_type": "execution_isolation_unavailable",
                    }
                if execution.status == "timeout":
                    submission_timeouts += 1
                    continue
                worker = _worker_result(execution.stdout)
                if worker is None or worker.get("status") != "returned":
                    submission_errors += 1
                    continue
                if worker.get("value") == case["expected"]:
                    passed += 1
        return {
            "status": "completed",
            "tests_executed": len(tests),
            "passed": passed,
            "failed": len(tests) - passed,
            "patch_valid": passed == len(tests),
            "resolved": passed == len(tests),
            "submission_errors": submission_errors,
            "submission_timeouts": submission_timeouts,
        }

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

    def _persist_producer(
        self,
        run_id: str,
        spec_hash: str,
        code_revision: str,
        evaluation_started_at: datetime,
    ) -> EvidenceRef:
        manifest = {
            "producer_kind": "acr_local_add_evaluator",
            "schema_version": "1.0",
            "evaluator_version": "local_add_evaluator_v1",
            "code_revision": code_revision,
            "private_spec_sha256": spec_hash,
            "evaluation_started_at": evaluation_started_at.isoformat(),
        }
        raw = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
        ref = ingest_evaluator_bytes(raw, self._data_root, run_id, "/evaluation/producer-manifest")
        persist_evaluation_json(self._data_root, run_id, "producer_manifest.json", manifest)
        persist_evaluation_json(self._data_root, run_id, "producer_ref.json", ref)
        return ref


def _worker_result(stdout: bytes) -> dict[str, object] | None:
    """Extract the submission result without interpreting arbitrary stdout."""

    for line in reversed(stdout.decode(errors="replace").splitlines()):
        if line.startswith("ACR_RESULT="):
            try:
                value = json.loads(line.removeprefix("ACR_RESULT="))
            except json.JSONDecodeError:
                return None
            return value if isinstance(value, dict) else None
    return None
