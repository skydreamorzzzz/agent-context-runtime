# Current milestone: M2/M3 real-loop integrity closure

M0 and M1 are DONE. M2 capture/evaluation and the first M3 noop A/A harness
are accepted, but this gate closes the minimum real coding loop needed before
any context-necessity experiment: model-directed read/write/test, reconstructible
seal, persisted usage, and semantic-condition-to-execution pair audit.

New integrity gates are cumulative. Do not delete, weaken, replace, or stop
executing any established M0/M1/M2 invariant or regression merely to satisfy a
new M3 gate.

## Required gates

- The add-task runtime remains a bounded synchronous loop (at most five
  physical attempts and tool steps): model-directed `read_file`, `write_file`,
  and public `run_test` only. A text answer is not a solved submission.
- Every runtime-built request records ordered `ContextBlock` occurrences. A
  tool-result block must bind its exact `tool_finish`, `tool_call_id`, and file
  binding; content equality never substitutes for occurrence identity.
- Sealing stores an immutable manifest plus regular-file body blobs. Evaluation
  materializes an isolated submission from those blobs, never from the live
  execution workspace. Submission syntax/import/runtime errors are completed
  task failures; evaluator protocol failures alone are `infra_error`.
- Events and snapshots have append-only journals before seal. Interrupted runs
  are not resumed, but prior observations remain available for audit.
- Usage ledger entries and a run aggregate are derived only from persisted
  provider usage evidence; absent fields and money remain unknown.
- Pair audit binds frozen provider/model/base URL/noop/cache/budget/runtime
  revision/evaluator revision/private-spec hash to both persisted runs and
  evaluations, not merely to A/A manifest equality.

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
