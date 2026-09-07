"""Small, sequential noop A/A pair harness; deliberately not an experiment framework."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from acr.contracts import EvidenceRef, Fact, Pair, Run
from acr.evaluation import LocalAddEvaluator
from acr.runtime.runner import (
    CapturedRuntime,
    DeepSeekSmokeOutcome,
    RuntimeTask,
    run_deepseek_add_smoke,
)
from acr.state import initial_tree_manifest
from acr.store import ingest_bytes, load_pair_json, persist_pair_json

PAIR_RUNTIME_VERSION = "m3_noop_pair_v1"
EVALUATOR_VERSION = "local_add_evaluator_v1"


class PairPreflightBlocked(ValueError):
    """Raised before a pair's first provider invocation."""


@dataclass(frozen=True)
class NoopPairPlan:
    pair: Pair
    manifest_ref: EvidenceRef
    source_tree_hash: str
    workspace_a: Path
    workspace_b: Path


@dataclass(frozen=True)
class NoopPairOutcome:
    pair: Pair
    run_a: Run
    run_b: Run
    outcome_a: DeepSeekSmokeOutcome
    outcome_b: DeepSeekSmokeOutcome


def canonical_semantic_config(
    *,
    config: dict[str, object],
    task_manifest_bytes: bytes,
    source_tree_hash: str,
    code_revision: str,
    private_spec_sha256: str,
) -> dict[str, object]:
    """Return the occurrence-free condition identity for one noop arm."""

    budget = config.get("budget")
    if not isinstance(budget, dict):
        raise PairPreflightBlocked("pair budget is malformed")
    required = ("provider", "model", "base_url", "task_manifest", "intervention", "cache_isolation")
    if any(not isinstance(config.get(key), str) or not config[key] for key in required):
        raise PairPreflightBlocked("pair configuration is incomplete")
    if config.get("intervention") != "noop":
        raise PairPreflightBlocked("A/A requires noop intervention for both arms")
    if budget.get("hard_max_physical_attempts") != 5:
        raise PairPreflightBlocked("pair physical-attempt budget is not frozen")
    return {
        "provider": config["provider"],
        "model": config["model"],
        "base_url": config["base_url"],
        "task_manifest_sha256": hashlib.sha256(task_manifest_bytes).hexdigest(),
        "task_source_tree_hash": source_tree_hash,
        "runtime_code_revision": code_revision,
        "evaluator_version": EVALUATOR_VERSION,
        "private_spec_sha256": private_spec_sha256,
        "attempt_budget": {"hard_max_physical_attempts": budget["hard_max_physical_attempts"]},
        "intervention": "noop",
        "cache_isolation": config["cache_isolation"],
    }


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _workspace_identity(path: Path) -> str:
    """Execution location identity, intentionally separate from tree content identity."""

    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()


def _pair_producer_ref(data_root: Path, pair_id: str, code_revision: str) -> EvidenceRef:
    manifest = {
        "producer_kind": "acr_noop_pair_harness",
        "schema_version": "1.0",
        "runtime_version": PAIR_RUNTIME_VERSION,
        "code_revision": code_revision,
    }
    raw = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    ref = ingest_bytes(raw, data_root, "acr_pair_producer", pair_id, "/producer-manifest")
    persist_pair_json(data_root, pair_id, "producer_manifest.json", manifest)
    persist_pair_json(data_root, pair_id, "producer_ref.json", ref)
    return ref


def prepare_noop_pair(
    *,
    data_root: Path,
    pair_id: str,
    replicate_id: str,
    task_id: str,
    config: dict[str, object],
    task_manifest_bytes: bytes,
    source_workspace: Path,
    workspace_root: Path,
    code_revision: str,
    private_spec_sha256: str,
    execution_order: str,
) -> NoopPairPlan:
    """Freeze and persist pair identity before any provider invocation."""

    if execution_order not in {"AB", "BA"}:
        raise PairPreflightBlocked("pair execution order is invalid")
    source_tree, source_tree_hash = initial_tree_manifest(source_workspace)
    del source_tree
    run_a, run_b = f"{pair_id}-A", f"{pair_id}-B"
    workspace_a, workspace_b = workspace_root / pair_id / "A", workspace_root / pair_id / "B"
    if workspace_a == workspace_b or workspace_a.exists() or workspace_b.exists():
        raise PairPreflightBlocked("fresh pair workspaces are unavailable")
    semantic = canonical_semantic_config(
        config=config,
        task_manifest_bytes=task_manifest_bytes,
        source_tree_hash=source_tree_hash,
        code_revision=code_revision,
        private_spec_sha256=private_spec_sha256,
    )
    semantic_hash = hashlib.sha256(_canonical_bytes(semantic)).hexdigest()
    manifest = {
        "pair_id": pair_id,
        "replicate_id": replicate_id,
        "task_id": task_id,
        "baseline_run_id": run_a,
        "treatment_run_id": run_b,
        "execution_order": execution_order,
        "mode": "from_scratch",
        "source_tree_hash": source_tree_hash,
        "semantic_config_A": semantic,
        "semantic_config_B": semantic,
        "semantic_config_hash_A": semantic_hash,
        "semantic_config_hash_B": semantic_hash,
        "workspace_identity_A": _workspace_identity(workspace_a),
        "workspace_identity_B": _workspace_identity(workspace_b),
    }
    manifest_raw = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    manifest_ref = ingest_bytes(manifest_raw, data_root, "acr_pair_manifest", pair_id, "/pair-manifest")
    producer_ref = _pair_producer_ref(data_root, pair_id, code_revision)
    pair = Pair(
        kind="pair",
        id=pair_id,
        producer_ref=producer_ref,
        provenance_ref=manifest_ref,
        task_id=task_id,
        replicate_id=replicate_id,
        baseline_run_id=run_a,
        treatment_run_id=run_b,
        manifest_hash=hashlib.sha256(manifest_raw).hexdigest(),
        execution_order=execution_order,
        preflight_result=Fact[bool](value=True, status="observed", refs=[manifest_ref]),
        status="prepared",
    )
    persist_pair_json(data_root, pair_id, "pair_manifest.json", manifest)
    return NoopPairPlan(pair, manifest_ref, source_tree_hash, workspace_a, workspace_b)


def run_noop_pair(
    *,
    plan: NoopPairPlan,
    data_root: Path,
    task: RuntimeTask,
    runtime_config_bytes: bytes,
    provider_factory,
    model: str,
    source_workspace: Path,
    private_spec: Path,
) -> NoopPairOutcome:
    """Run exactly two independent fresh noop arms and then persist the sealed pair."""

    shutil.copytree(source_workspace, plan.workspace_a)
    shutil.copytree(source_workspace, plan.workspace_b)
    if initial_tree_manifest(plan.workspace_a)[1] != plan.source_tree_hash or initial_tree_manifest(plan.workspace_b)[1] != plan.source_tree_hash:
        raise PairPreflightBlocked("fresh workspace initial tree differs from frozen source")

    runtimes = {
        "A": CapturedRuntime(data_root=data_root, run_id=plan.pair.baseline_run_id, task=task, workspace=plan.workspace_a, config_bytes=runtime_config_bytes, runtime_level="real_provider_aa_noop"),
        "B": CapturedRuntime(data_root=data_root, run_id=plan.pair.treatment_run_id, task=task, workspace=plan.workspace_b, config_bytes=runtime_config_bytes, runtime_level="real_provider_aa_noop"),
    }
    outcomes: dict[str, DeepSeekSmokeOutcome] = {}
    for arm in plan.pair.execution_order:
        outcomes[arm] = run_deepseek_add_smoke(runtimes[arm], provider_factory(), model=model)
        LocalAddEvaluator(data_root=data_root, sealed_workspace=(plan.workspace_a if arm == "A" else plan.workspace_b)).evaluate(outcomes[arm].run, str(private_spec))
    completed = plan.pair.model_copy(update={"status": "completed"})
    persist_pair_json(data_root, plan.pair.id, "pair.json", completed)
    return NoopPairOutcome(completed, outcomes["A"].run, outcomes["B"].run, outcomes["A"], outcomes["B"])


def load_pair(data_root: Path, pair_id: str) -> Pair:
    return Pair.model_validate(load_pair_json(data_root, pair_id, "pair.json"))
