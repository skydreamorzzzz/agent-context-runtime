"""Real Linux isolation regressions for runtime and evaluator submission code."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acr.audit import audit_evaluation, audit_run
from acr.evaluation import LocalAddEvaluator
from acr.execution import IsolationUnavailable, run_isolated_python
from acr.runtime.runner import CapturedRuntime, RuntimeTask
from acr.store import load_blob


def _runtime(tmp_path: Path, target: str) -> CapturedRuntime:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "target.py").write_text(target)
    return CapturedRuntime(
        data_root=tmp_path / "data",
        run_id="isolated-run",
        task=RuntimeTask("public/add", "public add task"),
        workspace=workspace,
        config_bytes=b'{}',
    )


def _sealed_run(tmp_path: Path, target: str):
    runtime = _runtime(tmp_path, target)
    return runtime, runtime.seal(status="completed")


def test_runtime_test_hides_host_environment_and_outside_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = "SHOULD_NOT_BE_VISIBLE"
    monkeypatch.setenv("DEEPSEEK_API_KEY", marker)
    monkeypatch.setenv("HOST_PRIVATE_PATH", str(tmp_path / "secret.txt"))
    (tmp_path / "secret.txt").write_text(marker)
    target = """
import os
from pathlib import Path

def add(a, b):
    leaked_env = "DEEPSEEK_API_KEY" in os.environ
    try:
        Path("../secret.txt").read_text()
        leaked_file = True
    except OSError:
        leaked_file = False
    return -999 if leaked_env or leaked_file else a + b
"""
    runtime = _runtime(tmp_path, target)
    result = runtime.tools.run_test()
    assert result.value["status"] == "completed"
    assert result.value["result"] == {"passed": True, "status": "completed"}
    runtime.seal(status="completed")
    assert audit_run(tmp_path / "data", "isolated-run").status == "PASS"
    assert not any(
        marker.encode() in path.read_bytes()
        for path in (tmp_path / "data").rglob("*")
        if path.is_file()
    )


def test_runtime_test_disables_network_and_leaves_no_python_cache(tmp_path: Path) -> None:
    target = """
import socket

def add(a, b):
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=0.1)
    except OSError:
        return a + b
    return -999
"""
    runtime = _runtime(tmp_path, target)
    result = runtime.tools.run_test()
    assert result.value["result"] == {"passed": True, "status": "completed"}
    assert not (runtime.workspace / "__pycache__").exists()


def test_runtime_test_kills_import_loop_and_bounds_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("acr.runtime.tools.PUBLIC_TEST_TIMEOUT_SECONDS", 0.1)
    runtime = _runtime(tmp_path / "timeout", "while True:\n    pass\n")
    timed_out = runtime.tools.run_test()
    assert timed_out.value["status"] == "timeout"
    runtime.seal(status="task_failed", stop_reason="public_test_timeout")
    assert audit_run(tmp_path / "timeout" / "data", "isolated-run").status == "PASS"

    workspace = tmp_path / "output"
    workspace.mkdir()
    execution = run_isolated_python(
        workspace,
        'print("A" * 1000000)',
        output_limit=1024,
    )
    assert execution.stdout_truncated is True
    assert len(execution.stdout) == 1024


def test_evaluator_submission_cannot_observe_private_spec_or_trusted_process(
    tmp_path: Path,
) -> None:
    marker = "PRIVATE_EVALUATOR_ONLY"
    target = f"""
import os
from pathlib import Path

def add(a, b):
    visible = list(os.environ.values()) + list(__import__("sys").argv)
    for path in (Path("/proc/1/cmdline"), Path("/proc/1/environ")):
        try:
            visible.append(path.read_text(errors="ignore"))
        except OSError:
            pass
    leaked = any({marker!r} in value for value in visible)
    leaked = leaked or Path("/private_eval").exists() or Path("/data").exists()
    return leaked
"""
    runtime, run = _sealed_run(tmp_path, target)
    private = tmp_path / "private-spec.json"
    private.write_text(
        json.dumps(
            {
                "private_marker": marker,
                "tests": [{"args": [1, 2], "expected": False}],
            }
        )
    )
    result = LocalAddEvaluator(
        data_root=runtime.data_root,
        code_revision="a" * 40,
    ).evaluate(run, str(private))
    assert result.status == "completed"
    assert result.resolved.value is True
    assert audit_evaluation(runtime.data_root, run.id, str(private)).status == "PASS"
    raw = load_blob(runtime.data_root, result.raw_result_ref.blob_hash)
    assert marker.encode() not in raw


def test_evaluator_submission_timeout_is_completed_task_failure(tmp_path: Path) -> None:
    runtime, run = _sealed_run(tmp_path, "while True:\n    pass\n")
    private = tmp_path / "private.json"
    private.write_text('{"tests":[{"args":[1,2],"expected":3}]}')
    result = LocalAddEvaluator(
        data_root=runtime.data_root,
        code_revision="a" * 40,
        timeout_seconds=0.1,
    ).evaluate(run, str(private))
    assert result.status == "completed"
    assert result.resolved.value is False
    raw = json.loads(load_blob(runtime.data_root, result.raw_result_ref.blob_hash))
    assert raw["submission_timeouts"] == 1
    assert audit_evaluation(runtime.data_root, run.id, str(private)).status == "PASS"


def test_true_isolation_failure_remains_evaluator_infra_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, run = _sealed_run(tmp_path, "def add(a, b):\n    return a + b\n")
    private = tmp_path / "private.json"
    private.write_text('{"tests":[{"args":[1,2],"expected":3}]}')

    def unavailable(*args, **kwargs):
        del args, kwargs
        raise IsolationUnavailable("fixture unavailable")

    monkeypatch.setattr("acr.evaluation.run_isolated_python", unavailable)
    result = LocalAddEvaluator(
        data_root=runtime.data_root,
        code_revision="a" * 40,
    ).evaluate(run, str(private))
    assert result.status == "infra_error"
    assert result.resolved.status == "unknown"
