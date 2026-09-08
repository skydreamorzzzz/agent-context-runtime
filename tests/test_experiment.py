"""Persisted M3 noop A/A pair-harness regressions; no network calls."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from acr.adapters.provider import CapturedProvider, TransportResult
from acr.audit import audit_pair
from acr.evaluation import LocalAddEvaluator
from acr.experiment import prepare_noop_pair
from acr.runtime.runner import CapturedRuntime, RuntimeTask
from acr.store import ingest_runtime_bytes, persist_pair_json


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def _complete_pair(tmp_path: Path) -> tuple[Path, Path, str]:
    source = tmp_path / "source"
    source.mkdir(parents=True)
    (source / "target.py").write_text("def add(a, b):\n    pass\n")
    private = tmp_path / "private.json"
    private.write_text(json.dumps({"tests": [{"args": [1, 2], "expected": 3}]}))
    config = {
        "provider": "deepseek", "model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com",
        "task_manifest": "public.json", "intervention": "noop", "cache_isolation": "unsupported",
        "budget": {"hard_max_physical_attempts": 5, "target_physical_attempts": 2},
    }
    root = tmp_path / "data"
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    plan = prepare_noop_pair(
        data_root=root, pair_id="pair-1", replicate_id="aa-1", task_id="public/add",
        config=config, task_manifest_bytes=b'{"task_id":"public/add"}', source_workspace=source,
        workspace_root=tmp_path / "workspaces", code_revision=revision,
        private_spec_sha256=hashlib.sha256(private.read_bytes()).hexdigest(), execution_order="AB",
    )
    for arm, workspace, run_id in (("A", plan.workspace_a, plan.pair.baseline_run_id), ("B", plan.workspace_b, plan.pair.treatment_run_id)):
        del arm
        shutil.copytree(source, workspace)
        runtime = CapturedRuntime(
            data_root=root, run_id=run_id, task=RuntimeTask("public/add", "Read target.py"),
            workspace=workspace,
            config_bytes=json.dumps({**config, "code_revision": revision}, sort_keys=True).encode(),
        )
        provider = CapturedProvider(lambda body, attempt: TransportResult("ok", b'{"id":"response"}'))
        runtime.tools.read_file("target.py")
        runtime.send_request(provider, b'{"request":"same"}', "call-1")
        run = runtime.seal(status="completed")
        LocalAddEvaluator(data_root=root, sealed_workspace=workspace, code_revision=revision).evaluate(run, str(private))
    persist_pair_json(root, plan.pair.id, "pair.json", plan.pair.model_copy(update={"status": "completed"}))
    assert audit_pair(root, plan.pair.id, str(private)).status == "PASS"
    return root, private, plan.pair.id


def test_noop_pair_persisted_audit_closes_two_fresh_runs(tmp_path: Path) -> None:
    root, private, pair_id = _complete_pair(tmp_path)
    assert audit_pair(root, pair_id, str(private)).status == "PASS"


def test_pair_budget_ignores_nonsemantic_fields_but_binds_hard_maximum(tmp_path: Path) -> None:
    root, private, pair_id = _complete_pair(tmp_path)
    assert audit_pair(root, pair_id, str(private)).status == "PASS"
    replacement = {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "task_manifest": "public.json",
        "intervention": "noop",
        "cache_isolation": "unsupported",
        "budget": {"hard_max_physical_attempts": 4, "target_physical_attempts": 2},
        "code_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
    }
    raw = json.dumps(replacement, sort_keys=True).encode()
    for run_id in (f"{pair_id}-A", f"{pair_id}-B"):
        ref = ingest_runtime_bytes(raw, root, run_id, "/config")
        run_path = root / "runs" / run_id / "run.json"
        run = json.loads(run_path.read_text())
        run["config_ref"] = ref.model_dump()
        _write_json(run_path, run)
        requests_path = root / "runs" / run_id / "requests.jsonl"
        requests = [json.loads(line) for line in requests_path.read_text().splitlines()]
        for request in requests:
            request["model_config_ref"] = ref.model_dump()
        requests_path.write_text("".join(json.dumps(item) + "\n" for item in requests))
    assert "pair_actual_execution_binding_mismatch" in audit_pair(
        root, pair_id, str(private)
    ).blocks


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("same_run", "pair_same_run"),
        ("task", "pair_task_identity_mismatch"),
        ("semantic", "pair_semantic_config_mismatch"),
        ("intervention", "pair_semantic_config_mismatch"),
        ("source", "pair_initial_state_mismatch"),
        ("execution_order", "pair_manifest_run_binding_mismatch"),
        ("manifest", "pair_manifest_hash_mismatch"),
        ("swapped", "pair_manifest_run_binding_mismatch"),
    ],
)
def test_pair_mutations_block_persisted_audit(tmp_path: Path, mutation: str, reason: str) -> None:
    root, private, pair_id = _complete_pair(tmp_path)
    pair_path = root / "pairs" / pair_id / "pair.json"
    manifest_path = root / "pairs" / pair_id / "pair_manifest.json"
    pair, manifest = json.loads(pair_path.read_text()), json.loads(manifest_path.read_text())
    if mutation == "same_run":
        pair["treatment_run_id"] = pair["baseline_run_id"]
    elif mutation == "task":
        pair["task_id"] = "other/task"
    elif mutation == "semantic":
        manifest["semantic_config_B"]["model"] = "other-model"
    elif mutation == "intervention":
        manifest["semantic_config_B"]["intervention"] = "not-noop"
    elif mutation == "source":
        manifest["source_tree_hash"] = "0" * 64
    elif mutation == "execution_order":
        pair["execution_order"] = "BA"
    elif mutation == "manifest":
        manifest["replicate_id"] = "tampered"
    elif mutation == "swapped":
        pair["baseline_run_id"], pair["treatment_run_id"] = pair["treatment_run_id"], pair["baseline_run_id"]
    if mutation in {"same_run", "task", "execution_order", "swapped"}:
        _write_json(pair_path, pair)
    else:
        _write_json(manifest_path, manifest)
    assert reason in audit_pair(root, pair_id, str(private)).blocks


def test_pair_audit_blocks_runtime_and_evaluation_regressions(tmp_path: Path) -> None:
    root, private, pair_id = _complete_pair(tmp_path / "runtime")
    events = root / "runs" / f"{pair_id}-A" / "events.jsonl"
    events.write_text("")
    assert "pair_run_audit_block" in audit_pair(root, pair_id, str(private)).blocks

    root, private, pair_id = _complete_pair(tmp_path / "evaluation")
    result = root / "evaluations" / f"{pair_id}-B" / "evaluation_result.json"
    value = json.loads(result.read_text())
    value["resolved"]["value"] = True
    _write_json(result, value)
    assert "pair_evaluation_audit_block" in audit_pair(root, pair_id, str(private)).blocks


def test_pair_audit_blocks_private_spec_and_evaluator_version_divergence(tmp_path: Path) -> None:
    root, private, pair_id = _complete_pair(tmp_path / "spec")
    private.write_text(json.dumps({"tests": [{"args": [9, 9], "expected": 18}]}))
    assert "pair_evaluation_audit_block" in audit_pair(root, pair_id, str(private)).blocks

    root, private, pair_id = _complete_pair(tmp_path / "version")
    result = root / "evaluations" / f"{pair_id}-A" / "evaluation_result.json"
    value = json.loads(result.read_text())
    value["evaluator_revision"] = "local_add_evaluator_v2"
    _write_json(result, value)
    assert "pair_evaluation_audit_block" in audit_pair(root, pair_id, str(private)).blocks
