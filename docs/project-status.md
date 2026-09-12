# Project status

## Active Track — Agent Forensics

- Active MVP hypothesis: Agent Forensics
- Status: SELECTED FOR VALIDATION
- Implementation: STATIC DEMO + LOCAL OPT-IN DEMO RAW CAPTURE
- Product validation: NOT ESTABLISHED
- Research novelty: NOT ESTABLISHED
- F0: PASS
- Pre-F0.5 integrity correction: PASS
- F0.5: PASS
- F1 Product Core Foundation: PASS
- Demo Visualization Slice: PASS
- F2 Failure Boundary: DEFERRED / NOT STARTED
- Workspace Fork: NOT STARTED
- Incident Theater: NOT STARTED

F0 added five provisional Forensics record types in
`src/acr/forensics_contracts.py`, a content-addressed synthetic incident fixture,
and contract/claim-boundary tests. This proves only that a concrete provisional
model can express and round-trip the synthetic incident. It does not validate
Claude interfaces, real checkpoint capture, verifier execution or binding,
restore/fork fidelity, analyzer behavior, or product claims.

The Pre-F0.5 integrity correction separates canonical captured-state identity
from checkpoint occurrence metadata, makes the manifest deterministic over Git
base plus captured overlay, enforces manifest reference/hash equality, restricts
report capture gaps to false/unknown entries, and corrects the active
architecture/control-plane guidance. `WorkspaceCheckpoint` now recomputes the
canonical state hash and binds both stored manifest hash fields to it. The
recorded full local repository result is 141 tests PASS with Ruff PASS. This is
internal F0 consistency evidence only, not Reality Spike or operational
feasibility evidence.

The initial F0.5 evidence independently demonstrated the Claude PASS-to-FAIL and
Git restore components. The accepted conditional closure then restored the
passing captured state from the same real Claude incident and manifest-verified
it. Executable state now participates in canonical identity for captured
present regular files and was restored in both directions for tracked and
selected-untracked paths. The recorded verdict is:

> **F0.5 Reality Spike: PASS**

F0.5 used minimum disposable probes under
[`docs/f0.5-reality-spike.md`](f0.5-reality-spike.md). It is not product
implementation and does not establish product demand, general architectural
feasibility, complete restoration fidelity, causal analysis, or research
novelty. The closure establishes captured repository scope only in the tested
Claude Code 2.1.144 and Ubuntu/WSL2 environment; it was not a production
Workspace Fork or complete workspace restoration.

Recorded final local conditional-closure result: 151 tests PASS; Ruff PASS. No
repository workflow files were present, so this is not described as GitHub CI
evidence.

F1 freezes only the production semantics required by `AgentEvent`,
`WorkspaceCheckpoint`, `VerificationReceipt`, `CapturedPathState`, capture
scope, and canonical captured-state identity. Historical F0 primary records
remain readable with their provisional marker; `IncidentReport` and
`ForkReceipt` remain provisional.

The production entry point is `acr claude`. It supplies additive hooks through a
temporary Claude `--settings` file and does not overwrite user or repository
Claude configuration. The adapter persists sanitized stable events; the
checkpoint runtime independently captures repository files rather than source
content from Claude tool payloads. Exact verifier pre/result events are joined
only with same-session and same-tool-use correlation, and every receipt resolves
to the tested pre-checkpoint and identical manifest hash. Frozen receipts enforce
PASS as observed exit 0 and FAIL as an observed non-zero exit. Unclassified
failure and interruption events persist without being promoted to receipts.
Trusted capture is limited to the validated Claude Code 2.1.144 on Ubuntu/WSL2
profile.

The corrected committed F1 smoke under `docs/receipts/f1_product_core` used one
real Claude Code 2.1.144 production session on Ubuntu/WSL2. It observed exact
`pytest -q` PASS, an ordinary Claude Bash mutation of an existing tracked file,
and exact `pytest -q` exit-1 FAIL, producing 8 events, two checkpoints, and two
verification receipts. No Edit/Write event was recorded. The production session
audit and privacy scan passed, and both canonical manifest SHA256 values
recomputed exactly. It supersedes the prior unknown-exit smoke. Full local
regression: 166 tests PASS; Ruff PASS.

> **F1 Product Core Foundation: PASS**

The current demo-first strategy projects the committed F1 evidence through a
small Python builder into `demo/data/sessions.json`, then renders it with static
HTML, CSS, and vanilla JavaScript. The frontend consumes only that presentation
ViewModel. The first case shows the observed PASS-to-FAIL boundary, the
intervening Bash occurrence, the sole changed captured path `calculator.py`, and
a unified diff derived from captured content blobs.
The generated ViewModel contains one supported session and no skipped sessions.
Full local regression is 167 tests PASS with Ruff PASS; the static page and its
three resources returned HTTP 200 from Python's standard-library static server.

> **Demo Visualization Slice: PASS**

The static demo now has a separate, explicitly opted-in local research source:
`acr claude --demo-raw-capture` copies Claude Code's own session JSONL under
gitignored `.acr/demo-raw/<acr-session-id>/`, normalizes ordered user,
assistant, and tool steps, and runs two exact demo-only diagnostics. D01 marks a
later complete-request Read only when the same path has the exact same recorded
result; D02 marks a later exact repeated Bash command while excluding the
configured verifier. They are labeled W04-compatible and W06-compatible, not
as recovered implementations of the historical W rules.

One controlled local Claude Code 2.1.144 smoke recorded PASS, two identical
`git status --short` tool occurrences, a Bash mutation of existing tracked
`calculator.py`, and exit-1 FAIL. D02 produced one raw-derived yellow hit. Its
Claude `tool_use_id` exactly matched the F1 occurrence and projected to the
concrete F1 timeline step; the session audit passed. An attempted repeated-Read
smoke produced two Read occurrences but Claude returned a different deduplication
result for the second call, so D01 correctly emitted no hit. Raw transcripts
remain local and uncommitted. Full local regression: 174 tests PASS; Ruff PASS.

Formal Failure Window productization, Workspace Fork, restore, and
production-grade Incident Theater remain DEFERRED / NOT STARTED. Product
validation and research novelty remain NOT ESTABLISHED.

## Legacy Track — Context Optimization Research

M0: DONE
M1: DONE
M2 provider/runtime capture: PASS
M2 independent evaluator: PASS
M2 real coding-agent loop / reconstructible seal / usage ledger: PASS
M3 Noop/A-A paired-run feasibility: PASS
M3 semantic/execution binding and current-revision revalidation: PASS
M3 overall: IN PROGRESS
Pre-M4 trust closure: PASS
Execution/evaluator isolation closure: PASS
Offline duplicate-read candidate coverage audit: PASS (`NO_GO` for formal intervention)
M4: NOT STARTED

Latest implementation checkpoint: `290be9fdae521c6e7f48b528ba93997767232490` —
pinned Multi-SWE-bench Flash offline duplicate-read coverage scan and fail-closed
candidate predicate.

Current context/document baseline: repository HEAD.

The accepted M1 source fixture remains the official MSWE-agent demonstration
`marshmallow-code__marshmallow-1867.traj`.

The official Multi-SWE-bench Flash OpenHands archive is now available and was
scanned at pinned dataset revision `9180bb0c633e4580fc8f74629ac6a47b8582543f`.
Its 20,571,531 raw bytes match SHA256
`7f0b0c5b65bd019ee3971a1dca2fd087294396ebf347e5321fcc85ccbea024bf`;
258/258 contained JSON trajectories were readable. The scan found 58
trajectories with exact duplicate recorded read output, but zero strict legal
candidates because the historical format lacks exact source-file
bytes/encoding, actual request co-membership, and pre-send current-state
evidence. See `docs/coverage/multi-swe-bench-flash-duplicate-read-v1.md`.

M2 has a preserved local-only DeepSeek real smoke and an independently audited
private evaluator result. The raw runtime/evaluation evidence and private spec
are ignored and uncommitted.

One real DeepSeek `deepseek-v4-flash` noop A/A pair completed at clean revision
`a833b62`: two fresh independent workspaces, two sealed/evaluated runs, and a
persisted pair audit all passed. Provider-cache isolation remains unsupported.
This is a single-pair M3 feasibility result, not the frozen plan's full
multi-task M3 completion and not evidence of intervention effectiveness.

Current-revision real noop A/A revalidation `aa-isolation-1075710` passed: both
runs sealed before evaluation, both runtime audits and evaluation audits passed,
and persisted pair audit passed. Arm A used 4 physical attempts; arm B used the
frozen maximum of 5. Both independently read and wrote the public target and
resolved all three private cases. Raw evidence remains local-only and ignored.
That real validation is retained and was re-audited after the isolation
corrections; no repeat provider call was made. Offline regressions now prove
that submission workspaces are read-only, closed output pipes cannot bypass the
hard timeout, and pair ordering derives from persisted `run_stop.end` evidence.

Historical Flash evidence alone is `NO_GO` for formal
`omit_one_duplicate_read_v1` intervention. No request deletion or treatment
intervention is implemented; M4 remains NOT STARTED and is frozen. It is not the
current next gate.

Infrastructure P0 closure is frozen. It must not be reopened without a concrete
experiment-blocking regression.

Latest local-only real-loop attempt at clean revision `2844605` followed the
strict protocol through `READ`, explicit `WRITE`, `TEST`, and `FINAL`. It used
four physical attempts, changed the fresh workspace, sealed as `completed`, and
passed the persisted runtime audit. No evaluator was invoked by this smoke path.

The four confirmed code-level closure items are now covered: text-only answers
cannot edit the workspace, duplicate read messages retain exact occurrence
bindings, pair audit compares only the frozen hard attempt maximum, and CLI
acceptance uses the configured 1..hard-max range. No deletion/intervention was
implemented.

The task manifest's `public_instruction` now supplies the real loop's initial
user message; an offline transport regression verifies the exact sent request
body. Real-provider coding-loop validation is PASS.

Trust closure correction:

- state-check temporal attestation: PASS
- provenance anti-laundering: PASS
- pre-send FileComparison binding: PASS
