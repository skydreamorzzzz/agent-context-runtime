# Current milestone: M3 — Noop / A-A Paired-Run Feasibility

M0, M1, and M2 are DONE. This M3 gate is limited to one real DeepSeek noop
A/A pair. It validates a paired-run harness, not an intervention, benchmark,
or context-optimization result.

New integrity gates are cumulative. Do not delete, weaken, replace, or stop
executing any established M0/M1/M2 invariant or regression merely to satisfy a
new M3 gate.

## Required gates

- Persist the pair manifest before either physical provider request. It freezes
  pair/replicate/task IDs, both preallocated run IDs, provider/model, task
  manifest hash, source-tree hash, code revision, evaluator version,
  private-spec hash, noop intervention, attempt budget, cache limitation,
  execution order, and occurrence-free semantic config hashes for both arms.
- A and A' are both `noop`; their semantic configs must be byte-canonically
  equal. Run ID, time, provider ID, output, usage, and final artifact are
  execution occurrences and may differ. Do not describe their difference as an
  intervention effect.
- Copy the same frozen public source into two distinct fresh workspaces before
  requests. Both initial tree hashes must equal the source tree; execution
  workspace identities must be distinct and remain separate from tree identity.
- Each arm has a distinct runtime/provider capture instance, physical-attempt
  inventory, events, snapshots, workspace, seal, and independent evaluator
  execution. Each runtime and evaluation audit must PASS from persisted
  artifacts.
- Persist a completed `Pair` only after both arms/evaluations finish. Pair
  audit must close the exact manifest blob, pair producer blob, run identities,
  task/config/source equality, noop condition, execution order, runtime audits,
  and evaluation audits.
- Pair mutations must BLOCK through production persisted audit: same run twice,
  task/config/intervention/source mismatch, failed runtime/evaluation audit,
  private-spec/evaluator divergence, execution-order or manifest tamper, and
  arm occurrence swapping.
- Provider cache isolation remains `unsupported`; usage/cache differences are
  observations, not causal claims.

## Real A/A gate

Run only one pair, sequentially, with one provider/model/task and no more than
five physical attempts per arm. The public add task must produce at least one
exact `read_file` binding per arm. Real runtime/evaluator evidence and private
specs remain local-only and must never be committed. A clean Git worktree and
available non-secret credential are mandatory preflight conditions.

## Prohibited

No candidate detection, intervention, deletion/compression, paired treatment,
multiple replicates, benchmark execution, cost claims, A/A statistics, second
task/provider/model, parallel execution, framework/registry expansion, or M4
work.

## Completion rule

One successful real pair may be reported as `M3 Noop/A-A paired-run feasibility:
PASS`; M3 overall remains IN PROGRESS because frozen-plan M3 includes more
than one small task and no actual intervention has yet been authorized.
