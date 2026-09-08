# Current milestone: Execution/evaluator isolation closure

M0–M2 are DONE. M3 noop A/A feasibility has passed while M3 overall remains
IN PROGRESS. Pre-M4 evidence and visibility trust closure remains PASS. M4 is
NOT STARTED.

This gate closes the execution boundary required before any real intervention:

- Runtime public tests execute in Linux user/mount/PID/network namespaces with
  bubblewrap. The current workspace and minimum Python runtime are read-only;
  only sandbox-private `/tmp` is writable. The inherited host environment is
  cleared and network access is disabled.
- Runtime and evaluator submission execution have a hard wall-clock timeout and
  bounded stdout/stderr evidence. Process liveness remains authoritative even
  after output pipes close, and every post-timeout wait is bounded. Submission
  timeout is a task failure, not an evaluator infrastructure failure.
- The trusted evaluator reads private expected values only after seal. Each
  untrusted submission process receives public arguments only; it cannot see the
  private spec, runtime data root, host secrets, or trusted evaluator process.
- A noop pair seals both runtime arms before either private evaluation starts.
  Evaluator producer evidence records `evaluation_started_at`, and persisted
  pair audit requires both starts to follow the unique final completed
  `run_stop.end` occurrence in each persisted event stream. `Run.end` is not
  used to establish this phase boundary.
- The current-revision real noop A/A pair has passed both runtime audits, both
  evaluation audits, and pair audit. Provider-cache isolation remains
  unsupported and no causal claim is made. That previous real validation is
  retained; the read-only mount, hard-timeout, and authoritative-ordering
  corrections are closed by offline regressions without another paid run.
- All earlier M0–M3 and Pre-M4 integrity regressions remain cumulative.

## Completion

`EXECUTION_EVALUATOR_ISOLATION_CLOSURE_PASS`

Infrastructure P0 closure is frozen. Do not reopen P0 without a concrete
experiment-blocking regression.

Next gate: M4a deterministic duplicate-read candidate/intervention fixture.
Candidate detection, intervention, request deletion, treatment pairs, and
rebound measurement remain prohibited until explicitly authorized.
