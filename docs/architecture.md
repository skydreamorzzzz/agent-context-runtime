# Architecture and dependency boundaries

## Status and authority

This page summarizes the Agent Forensics architecture selected for validation.
F1 implements and freezes the narrow production path from sanitized Claude hooks
through exact-verifier pre-state checkpoints and verification receipts.
Restoration, Failure Window analysis, frontend behavior, and broader concurrency
remain provisional or not started. The active authority is
[`agent-forensics-mvp-plan.md`](../agent-forensics-mvp-plan.md).

No operational component in the active flow below is implemented merely because
its F0 record shape appears in this diagram.

## Active flow

```text
Claude Hooks (temporary production settings)
     │
     ▼
Claude-specific adapter
     │
     ▼
AgentEvent Journal
     │
     └── exact verifier PreToolUse ─────────────► Pre-Verifier WorkspaceCheckpoint
     │                                                  │
     └── matched verifier execution/result ────────────┤
                                                        ▼
                                              VerificationReceipt

AgentEvent Journal
        +
WorkspaceCheckpoint
        +
VerificationReceipt
        │
        ▼
 Incident Analyzer
        │
        ▼
 IncidentReport
        │
        ▼
 Incident Theater

Selected WorkspaceCheckpoint
        │
        ▼
 Workspace Fork
        │
        ▼
 ForkReceipt
```

Primary append-only evidence is `AgentEvent`, `WorkspaceCheckpoint`, and
`VerificationReceipt` for the frozen F1 runtime slice. `IncidentReport` is a
recomputable, analyzer-version-dependent derived view. `ForkReceipt` is an
action receipt. Their F0 shapes round-trip a synthetic incident; F1 does not
freeze or implement the derived report or action path.

Event occurrence is not checkpoint materialization. A journal event may create
a checkpoint opportunity without causing repository-state evidence to be
materialized. F1 materializes checkpoints only for root-scoped, foreground,
byte-exact configured verifier `PreToolUse` events.

A `VerificationReceipt` requires both captured pre-verifier state and matched
verifier execution/result evidence. The F1 session integrity boundary resolves
the pre-checkpoint in the same session, compares manifest hashes, and requires
the same hashed Claude session and tool-use occurrence. It emits no trusted
receipt when that correlation cannot be proved.

`WorkspaceCheckpoint` is the restoration authority for a future Workspace
Fork. An `IncidentReport` may select or reference a checkpoint, but as a derived
view it is not restoration authority.

The analyzer and frontend must not depend directly on raw Claude payloads. The
frontend is a read-only legibility layer, not evidence authority. It cannot
create evidence, alter truth, or promote heuristics to observed facts.

## State and verification boundaries

`captured_workspace_manifest_hash` identifies only the explicitly captured
repository scope. Capture policy must record included paths, excluded or
unsupported areas, truncation, and completeness gaps. It does not capture or
represent complete environment, process, network, database, machine, or model
state.

The F1-compatible manifest hashes deterministic canonical bytes containing Git
base identity plus a path-ordered captured overlay: repository-relative path,
tracked or selected-untracked classification, present or deleted state, and
content hash plus executable boolean when a regular file is present. Deleted
paths use not-applicable executable state. This is not a generic POSIX mode
model. The manifest excludes checkpoint ID, session ID, ordering, timestamp,
trigger, event ID, evidence locator, and incident metadata. Thus, identical
captured state can share one manifest hash across distinct checkpoint
occurrences; occurrence identity remains in each checkpoint record.

Verifier evidence is intended to bind to a forced pre-execution checkpoint:

```text
captured pre-state A → verifier execution/result → optional post-state B
```

The verifier may mutate the tree, so B cannot be substituted for the tested
state A. F1 production code enforces this binding for the explicitly configured
exact verifier in the supported one-session boundary.

Privacy exclusions override reconstruction completeness. An exclusion records a
capture gap and degrades completeness; no component may bypass it.

## Execution boundary

The v0 target is one instrumented Claude Code session in one isolated Git
worktree. Exact attribution under multiple sessions, human edits, or background
writers is unsupported. Background execution may be recorded as observed while
mutation attribution is explicitly degraded.

The committed F1 smoke validates the required PreToolUse/PostToolUse and
PostToolUseFailure behavior on Claude Code 2.1.144. Other versions, background
execution attribution, and concurrent writers do not inherit that result.

## Reuse boundaries

Legacy concepts may be reused only after the active gate authorizes code work:

| Legacy asset | Reusable idea | Not yet established |
|---|---|---|
| `contracts.py` | strict/versioned models, `Fact`, evidence references, identity separation | frozen or reality-validated Forensics fields |
| `store.py` | immutable SHA256 blobs and references | multi-process journal safety |
| `state.py` | path safety and deterministic manifest/hash | dynamic checkpoints or restore fidelity |
| `experiment.py`, `evaluation.py` | controlled research/lab assets | active v0 product path |

Local JSON/JSONL and content-addressed blobs remain the storage boundary. Do not
add a database, registry, DI/plugin system, event bus, DAG engine, ORM, or
distributed orchestrator.

## Legacy Context Optimization architecture

The implemented historical flow remains:

```text
raw blob → normalize → provenance + audit → runtime events/request snapshots
         → DecisionView → Candidate → InterventionPlan/Receipt → sealed run
         → isolated evaluation + accounting → reproducible report
```

Its module boundaries and claims remain documented by the legacy
[`Context Optimization MVP plan`](../agent-context-runtime-mvp-plan.md),
[`observation protocol`](observation-protocol.md), and
[`audit checklist`](audit-checklist.md). That architecture is frozen as research
history and is not the active implementation roadmap.
