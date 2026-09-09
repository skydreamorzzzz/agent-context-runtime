# Agent Context Runtime: Stable Instructions

## Authority

The repository has two deliberately separate authority domains.

- **Active validation authority:** [`agent-forensics-mvp-plan.md`](agent-forensics-mvp-plan.md) governs current development. When another active document conflicts with it, report the conflict before expanding scope and follow the Forensics plan.
- **Historical authority:** [`agent-context-runtime-mvp-plan.md`](agent-context-runtime-mvp-plan.md), historical status documents, receipts, and coverage artifacts remain authoritative for interpreting the Legacy Context Optimization Research Track. Do not rewrite that track as Forensics work.

Agent Forensics is **SELECTED FOR MVP VALIDATION**. Its architecture, contracts,
checkpoint policy, verifier binding, restoration, and UI are not implemented or
validated. Product validation and research novelty are not established.

## Current gate and scope control

- The only next engineering gate is **F0 provisional contracts / fixture → F0.5 Reality Spike**.
- F0 defines tentative evidence contracts and a synthetic incident fixture. Every new Forensics contract remains provisional until F0.5 passes.
- F0.5 must verify current Claude Code interfaces and real runtime behavior, captured-scope repository round trips, verifier pre-state binding, operational safety, privacy gaps, and overhead before contracts or policies freeze.
- Do not begin F1 or later work before F0.5 PASS. In particular, do not build the Incident Theater, real hook capture, checkpointing, verifier integration, replay, or Workspace Fork early.
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
9. A Workspace Fork, if later validated, may claim only captured repository scope restoration and manifest verification—not deterministic replay, trajectory continuation, or complete workspace restoration.
10. Claude hook availability, payloads, ordering, batching, process lifecycle, correlation, background behavior, journal concurrency, verifier binding, Git base pinning, restore fidelity, and checkpoint overhead are external or operational assumptions until F0.5 validates them.

## Privacy and capture boundaries

Privacy constraints take precedence over reconstruction completeness.

- Exclude sensitive artifacts, record the capture gap, and degrade capture completeness. Never bypass an exclusion to improve reconstruction.
- Plan for `.acrignore`, sensitive default-deny patterns, blob and stdout/stderr caps, and explicit truncation, but do not build a complex redaction engine in advance.
- Do not record full prompts by default, environment-variable values, credentials, tokens, private-key contents, or proactively read `.env`.
- Unsupported or excluded environment, process, ignored-file, database, and network state must remain explicit `unsupported`, `unknown`, or `not captured` evidence gaps.

## Architectural constraints

- The active provisional evidence model has primary append-only `AgentEvent`, `WorkspaceCheckpoint`, and `VerificationReceipt`; derived `IncidentReport`; and action receipt `ForkReceipt`. Do not add these to Python contracts before the authorized F0 work, and do not freeze fields before F0.5 PASS.
- Keep Claude-specific payload translation at an adapter boundary. Analyzer and frontend must consume stable evidence/view models, not raw Claude payloads.
- A verifier receipt must bind the captured pre-execution repository state. A verifier may mutate the tree; an optional post-state is separate and cannot retroactively define the tested state.
- Event occurrence is not checkpoint materialization. Read/search events need not scan the repository. The concrete checkpoint policy remains provisional.
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
- Before completion: run relevant tests and lint, inspect the worktree, stage only reviewed paths, inspect the staged diff, commit only verified changes, and push only when requested or required.
- Changes to milestone state, implementation checkpoints, or handoff context must update `docs/project-status.md` in the same work session. Pure context commits may define their baseline as repository HEAD.
