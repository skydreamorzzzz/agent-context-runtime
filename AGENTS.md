# Agent Context Runtime: Stable Instructions

The frozen architecture baseline is `agent-context-runtime-mvp-plan.md`. When
code or a short status document conflicts with it, preserve the plan's research
discipline and report the conflict before expanding scope.

## Research discipline

- Build evidence before claiming benefit. Do not infer missing prompts, usage,
  state, cache state, provider behavior, or evaluation results.
- Preserve the chain: upstream source → immutable raw bytes/sha256 → normalized
  artifact → field provenance → audit → later runtime/evaluation/reporting.
- Content hash identifies bytes, not an occurrence. Preserve logical/event or
  source-location identity even when content repeats.
- `unknown`, `not_applicable`, and zero/false/empty are distinct. Observed and
  derived facts require evidence references; missing evidence must fail closed.
- Persistent top-level records use the `Envelope` conventions with schema
  version `1.0`. Reuse `acr.contracts.Provenance`; do not add parallel
  provenance schemas.
- Audit is fail-closed: a missing blob, hash mismatch, bad locator, missing or
  conflicting provenance, source/producer mismatch, or unverifiable observed
  claim is a BLOCK, never a silently repaired warning.

## Architecture boundaries

- Keep contracts, visibility, state, candidates, interventions, accounting,
  evaluation, and runtime logically independent. Evaluation is a separate
  process and private evaluator inputs never enter runtime.
- `ports.py` contains exactly the small `TrajectoryAdapter`, `Provider`,
  `Runtime`, and `Evaluator` Protocol boundaries. Do not add registries, DI,
  plugin systems, event buses, DAG engines, ORMs, or generic middleware.
- Use local JSON/JSONL and content-addressed blobs for the MVP. Do not add a
  database, dashboard, graph service, or distributed orchestrator.
- Historical array/message order is only `source_position`; never promote it to
  authoritative runtime sequence or future visibility without upstream proof.

## Milestone isolation

- Implement only the explicitly requested milestone. Do not start later
  runtime, provider, candidate, intervention, paired rerun, evaluator, or
  accounting work while an earlier gate remains open.
- Do not create synthetic evidence to replace unavailable upstream artifacts.
  Record unavailable inputs as blocked/unknown with their reason.
- Keep source manifests and producer manifests distinct: source explains raw
  origin; producer explains code/config/format that derived an artifact.
- Before claiming completion, run the requested tests and lint, inspect the
  worktree, commit only verified changes, and push when requested.
