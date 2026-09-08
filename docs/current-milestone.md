# Current milestone: Pre-M4 trust closure

M0 and M1 are DONE. M2 runtime/provider capture, the real coding loop, sealed
evaluation, and the first M3 noop A/A feasibility harness have passed their
recorded gates. M3 overall remains IN PROGRESS.

This gate closes the trust boundary required before candidate code may be
authorized. New integrity gates remain cumulative; no earlier M0–M3 regression
may be removed or weakened.

## Required gates

- `build_view(...)` admits only authorized public constants and completed
  same-run runtime evidence with `available_seq <= cutoff_seq`.
- Future, cross-run, evaluator/analysis, tainted, unknown-label, and unfinished
  evidence is rejected deterministically.
- Every runtime-built `ContextBlock` carries its exact origin: public system or
  task input, provider response occurrence, or completed tool occurrence.
- A historical complete UTF-8 `FileBinding` is compared with a safe current
  workspace re-read. The result is `same`, `changed`, or explicit `unknown`;
  only `same` can satisfy a later candidate precondition.
- Persisted DecisionView and FileComparison artifacts are checked through the
  production run audit for identity, visibility, occurrence, and byte/hash
  consistency.
- Existing command-loop, sealed-artifact, evaluation, accounting, and pair
  integrity regressions remain green.

## Prohibited

No candidate detector, intervention, deletion/replacement, treatment pair,
rebound measurement, native tool-calling framework, second provider/task, or
benchmark expansion is authorized in this milestone.

## Completion and next gate

When all gates pass, record `Pre-M4 trust closure: PASS`; do not mark M4
started. The next gate is execution/evaluator isolation closure, including
runtime execution isolation, evaluator isolation, timeout behavior, pair phase
ordering, and current-revision A/A revalidation.
