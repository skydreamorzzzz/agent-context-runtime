# Current milestone: M2.0 — Observation Protocol Freeze + Trusted Capture Slice

M1 remains DONE. M2 is authorized only for the minimal trusted-capture
vertical slice: protocol, persisted runtime evidence, send-boundary capture,
complete `read_file` binding, workspace verification, sealing, and adversarial
engineering tests. No context optimization or paired rerun is in scope.

New integrity gates are cumulative. Do not delete, weaken, replace, or stop
executing an already-established M1/M1.1 invariant or regression test merely
to satisfy a newer M1.2 gate.

## Required gates

- `docs/observation-protocol.md` freezes observation boundaries, raw evidence,
  status semantics, occurrence identity, contract binding, failure modes, and
  adversarial test for actual request, attempt, response, usage, tools, reads,
  state, final artifacts, and evaluation.
- Actual sent bytes are captured at the physical transport call, distinct from
  draft/prepared bytes. Every physical attempt is retained, including a thrown
  transport exception with failure evidence rather than a fake response.
- Physical-attempt inventory, snapshot, request-event, and terminal-event
  attempt sets must be exactly one-to-one. Each inventory record is producer/run
  bound, has the exact attempt sent-body locator, and carries a terminal
  response/failure reference that agrees with the terminal event. Usage facts
  must exactly resolve from their raw response `/usage`.
- Request before/prepared/sent evidence is occurrence-bound to its own attempt
  locator even when another attempt has identical bytes. Runtime producer and
  config refs must resolve to this run's persisted producer/config blobs; every
  snapshot must use `Run.config_ref`.
- Runtime events have authoritative serial `event_seq`; raw payloads precede
  normalized events. The audit reads persisted run artifacts only.
- `read_file` binds relative path, actual bytes, SHA256, UTF-8 full-read mode,
  read occurrence, run identity, and closed tool event.
- Initial workspace is verified without symlinks; protected data/evaluator roots
  cannot overlap workspace. Initial/final state hashes have separate semantics
  and raw refs; final tree/state binds to a sealed run.
- Evaluation remains outside runtime. No evaluator result may be fabricated.

## Retained M1/M1.1 regressions

- Source manifest completeness and raw-ref ↔ manifest `raw_sha256` binding.
- `source_id` / `trajectory_key` / instance identity consistency.
- Every provenance raw input ref must bind to this import's exact `raw_ref`
  blob hash, not merely to another valid blob with matching labels or content.
- The frozen MSWE-agent source type, repository, commit, artifact path, instance
  identity, and raw SHA256 must match their pinned values.
- Referenced raw blob exists and its hash matches.
- Invalid locator, wrong EvidenceRef blob hash, tampered normalized field,
  missing provenance, and conflicting provenance each BLOCK.
- Persisted artifact round-trip and immutable-write integrity.

## M2 adversarial and E2E gates

- Keep every M1/M1.1/M1.2 regression.
- Prepared/sent divergence, retry merge, lost failed attempt, missing usage
  default, usage value/ref/locator mutation, unfinished tool, file-byte replacement, same-path mutation,
  workspace escape, evaluator-root overlap, post-seal event, wrong-run ref,
  malformed persisted runtime evidence, state mismatch, and file-occurrence
  laundering must each reject or BLOCK.
- Run a clean engineering-fixture capture and persisted `audit-run`; it is not
  a real provider smoke.
- The first real-smoke command is fixed to the public DeepSeek add-task fixture.
  It is bounded to two requests (and never more than the frozen hard limit of
  five), requires an explicit model request for the sole `read_file`, and seals
  a task failure rather than retrying a nonconforming response.

## Prohibited

No duplicate detection, candidate, intervention, paired rerun, A/A, benchmark
execution, evaluator implementation, accounting, dashboard, learned policy,
second provider, or second task suite. Do not retry Flash or add a trajectory.

## Completion rule

An engineering fixture may validate capture wiring only. M2 stays IN PROGRESS
until a separately frozen, real provider/model/task/environment is available,
one real smoke is captured and sealed, and the required runtime/evaluator
conditions in the frozen MVP plan are met. A real task failure is evidence, not
an engineering failure, if capture and sealing remain complete.

The engineering integrity closure is complete: persisted audit now blocks
physical-inventory, request-occurrence, raw-usage, producer/config-reference,
state-reference/tree, and file-occurrence laundering.
