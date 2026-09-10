# Agent Context Runtime: Stable Instructions

## Authority

The repository has two deliberately separate authority domains.

- **Active validation authority:** [`agent-forensics-mvp-plan.md`](agent-forensics-mvp-plan.md) governs current development. When another active document conflicts with it, report the conflict before expanding scope and follow the Forensics plan.
- **Historical authority:** [`agent-context-runtime-mvp-plan.md`](agent-context-runtime-mvp-plan.md), historical status documents, receipts, and coverage artifacts remain authoritative for interpreting the Legacy Context Optimization Research Track. Do not rewrite that track as Forensics work.

Agent Forensics is **SELECTED FOR MVP VALIDATION**. F0 provisional contract
shapes and a synthetic fixture are implemented. F0.5 produced a CONDITIONAL
PASS for one narrow real Claude Code and Git happy path; the contracts remain
provisional and no production checkpoint, verifier, restore, analyzer, fork, or
UI capability is implemented. Product validation and research novelty are not
established.

## Current gate and scope control

- F0 provisional contracts and the synthetic incident fixture are PASS. This establishes testable schema semantics only; it does not validate operational feasibility.
- The Pre-F0.5 integrity correction is PASS. It strengthens internal F0 state-identity and validation semantics without adding real-world feasibility evidence.
- F0.5 Reality Spike is **CONDITIONAL PASS**. Gate A passed against Claude Code 2.1.144 and real Git in the narrow one-session, one-worktree, exact-verifier command path. Recorded observations and remaining boundaries are in `docs/f0.5-reality-spike.md`.
- The executable bit is not represented by the F0 manifest and was not restored by the disposable probe. Revise that captured-scope assumption or explicitly exclude it before the next MVP implementation gate. Contracts and policies remain provisional.
- F0.5 permits only the minimum experimental probe code needed to test real Claude interface behavior, captured-scope repository round trips, verifier binding, journal concurrency, checkpoint overhead, and Git durability. Probe code is not a public/product API, must not silently become production implementation or trigger F1+, and should remain isolated from the active production module surface where practical until the Reality Spike exits. Observations may inform later production design; probe architecture does not automatically become production architecture.
- F1 and later work remain NOT STARTED and require separate authorization after the conditional-pass revision is resolved. Do not build the Incident Theater, production hook capture/checkpointing/verifier integration, replay, or Workspace Fork early.
- The Legacy Context Optimization M4 and all duplicate-read intervention work are frozen. Do not implement request deletion or revive candidate/intervention experiments without separate reauthorization.
- Do not extend the active product path through `audit.py`, `candidates.py`, duplicate-read detection, interventions, DeepSeek experiments, provider request rewriting, or context-optimization policies. Preserve those files as legacy assets.
- Target v0.1 is one user, one Claude Code session, one isolated Git worktree, one local repository, explicitly configured verifiers, a local evidence store, and a local frontend. Do not broaden to concurrent writers, multiple providers/users, cloud services, or generic observability infrastructure.

## Evidence and claim discipline

1. Every conclusion must have traceable original evidence: source → SHA256 → normalized artifact → provenance → audit. Never infer missing prompts, state, cache, provider behavior, interface behavior, or results.
2. A content hash identifies bytes, not occurrences. Event/logical/source-location identity stays separate from content identity.
3. `unknown`, `not_applicable`, zero, empty, and false are distinct. Cognitive unknowns use explicit `Fact/status/reason` semantics, never magic strings.
4. Missing blobs, hash mismatches, invalid locators, absent/conflicting provenance, source/producer mismatches, or unverifiable observation claims BLOCK. Do not silently repair them.
5. Malformed persisted evidence produces deterministic BLOCK/AuditFinding outcomes. Malformed user input must not escape as unhandled parser, index, or key errors.
6. Distinguish Observed, Derived, Estimated, and Unknown. `IncidentReport` is an analyzer-version-dependent derived view; it is not primary evidence.
7. Use **Last Observed Passing State**, **First Observed Failing State**, and **Failure Window**. Do not claim “last good,” “first bad,” causal root cause, or global project correctness.
8. `captured_workspace_manifest_hash` covers only explicitly captured repository scope. Never describe it as complete repository, environment, process, machine, or model state.
9. Captured-state identity is separate from checkpoint occurrence identity. The canonical manifest includes Git base identity plus a deterministically ordered captured overlay; it excludes checkpoint ID, session ID, ordering, timestamp, trigger, event ID, and incident metadata. Identical captured state may therefore have one manifest hash across distinct checkpoint occurrences. `WorkspaceCheckpoint` validation recomputes this hash and requires both manifest hash fields to equal it.
10. A Workspace Fork, if later validated, may claim only captured repository scope restoration and manifest verification—not deterministic replay, trajectory continuation, or complete workspace restoration.
11. Treat F0.5 claims at their observed scope. The tested CLI exposed relevant hook boundaries, exact-command pre-state binding, a PASS-to-FAIL window, and captured-scope content restore. Other versions, prompt-level correlation, background mutation attribution, concurrent/shared-journal safety, executable mode, Git GC durability, and broader restore fidelity remain unsupported, degraded, or unknown as recorded in the Reality Spike log.

## Privacy and capture boundaries

Privacy constraints take precedence over reconstruction completeness.

- Exclude sensitive artifacts, record the capture gap, and degrade capture completeness. Never bypass an exclusion to improve reconstruction.
- Plan for `.acrignore`, sensitive default-deny patterns, blob and stdout/stderr caps, and explicit truncation, but do not build a complex redaction engine in advance.
- Do not record full prompts by default, environment-variable values, credentials, tokens, private-key contents, or proactively read `.env`.
- Unsupported or excluded environment, process, ignored-file, database, and network state must remain explicit `unsupported`, `unknown`, or `not captured` evidence gaps.

## Architectural constraints

- The F0 provisional evidence models live in `acr.forensics_contracts`: primary append-only `AgentEvent`, `WorkspaceCheckpoint`, and `VerificationReceipt`; derived `IncidentReport`; and action receipt `ForkReceipt`. They are synthetic-fixture-tested and selectively reality-challenged, but not frozen. Do not operationalize them until the conditional-pass revision is resolved and separately authorized.
- Keep Claude-specific payload translation at an adapter boundary. Analyzer and frontend must consume stable evidence/view models, not raw Claude payloads.
- A verifier receipt must bind the captured pre-execution repository state. A verifier may mutate the tree; an optional post-state is separate and cannot retroactively define the tested state.
- Cross-record verifier integrity belongs at a future evidence-set/journal boundary: `pre_checkpoint_id` must resolve in the same session, its manifest hash must equal the receipt's tested hash, and ordering/execution correlation must be valid. The standalone F0 receipt cannot prove those relations.
- Event occurrence is not checkpoint materialization. Read/search events need not scan the repository. The concrete checkpoint policy remains provisional.
- `WorkspaceCheckpoint` is restoration authority for a future Workspace Fork. `IncidentReport` may select or reference a checkpoint but is not restoration authority.
- The v0 execution contract is one instrumented Claude session per isolated worktree. Background execution may be observed while exact mutation attribution remains degraded.
- The frontend is a legibility layer, never evidence authority. It must not generate evidence, alter evidence truth, or present heuristics as facts.
- Reuse concepts from `contracts.py`, immutable content-addressed storage from `store.py`, and workspace/manifest safety ideas from `state.py` only after the relevant gate. Do not treat the existing initial-tree scan or unlocked append journal as a validated dynamic checkpoint design.
- Keep local JSON/JSONL plus content-addressed blobs. Do not add databases, registries, DI systems, plugin frameworks, event buses, DAG engines, ORMs, or distributed orchestration.
- Preserve source manifests and producer manifests as separate objects. Persistent top-level records continue to use the `Envelope` convention and existing `acr.contracts.Provenance` unless the active plan explicitly revises this after validation.

## Legacy invariants

The accepted Context Optimization research history remains factual: M0 DONE;
M1 DONE; M2 runtime/provider/evaluator gates PASS; one M3 noop A/A feasibility
PASS while M3 overall is incomplete; Pre-M4 trust closure PASS;
execution/evaluator isolation PASS; offline Multi-SWE-bench duplicate-read
coverage audit PASS with `NO_GO` for `omit_one_duplicate_read_v1`; M4 never
started; no real request-deletion treatment was implemented.

Do not remove or weaken legacy integrity gates or tests unless a later frozen
architecture explicitly replaces them and records the replacement. The legacy
runtime/provider/evaluator separation remains historical truth, but it is not
the active milestone chain. `experiment.py` and `evaluation.py` remain future
controlled-research assets, not the active v0 product path.

## Git and credential safety

- Use the repository's configured authenticated Git transport (credential helper or SSH agent).
- Never put PATs, tokens, passwords, or private-key material in commands, URLs, logs, documents, or commits. Never print, copy, or inspect credential values or key material.
- If authenticated transport is unavailable, stop and report: `push unavailable: authenticated Git transport not available`.
- Before committing, inspect the staged diff for `.env`, credentials, tokens, private keys, and key configuration. Do not force-push or rewrite history without explicit approval.
- Before completion: run relevant tests and lint, inspect the worktree, stage only reviewed paths, and inspect the staged diff. Every completed work round is committed and pushed to GitHub for user review unless the user explicitly says not to commit or not to push; verify that the remote branch SHA matches the local commit before reporting completion.
- Changes to milestone state, implementation checkpoints, or handoff context must update `docs/project-status.md` in the same work session. Pure context commits may define their baseline as repository HEAD.
