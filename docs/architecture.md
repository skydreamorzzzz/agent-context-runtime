# Architecture and dependency boundaries

## Status and authority

This page summarizes the **provisional Agent Forensics architecture** selected
for validation. F0 schema models and a synthetic fixture now exist. F0.5 PASS
demonstrated one narrow integrated disposable-probe path. Detailed production
interfaces, checkpoint policy, verifier binding, restoration, and concurrency
behavior remain provisional pending a separately authorized freeze. The active authority is
[`agent-forensics-mvp-plan.md`](../agent-forensics-mvp-plan.md).

No operational component in the active flow below is implemented merely because
its F0 record shape appears in this diagram.

## Provisional active flow

```text
Claude Hooks (narrow F0.5 observation; no production adapter)
     │
     ▼
Claude-specific adapter
     │
     ▼
AgentEvent Journal
     │
     ├── mutation-capable boundary ─────────────► WorkspaceCheckpoint
     │
     └── provisional verifier PreToolUse ───────► Pre-Verifier WorkspaceCheckpoint
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

Primary append-only evidence is tentatively `AgentEvent`,
`WorkspaceCheckpoint`, and `VerificationReceipt`. `IncidentReport` is a
recomputable, analyzer-version-dependent derived view. `ForkReceipt` is an
action receipt. Their F0 shapes round-trip a synthetic incident; F0.5 challenged
the narrow happy path, but every production object and interface remains
provisional pending a separate freeze.

Event occurrence is not checkpoint materialization. A journal event may create
a checkpoint opportunity without causing repository-state evidence to be
materialized. F0.5 observed exact-verifier `PreToolUse` capture and selected
tool boundaries on Claude Code 2.1.144; a concrete production checkpoint policy
remains provisional.

A `VerificationReceipt` requires both captured pre-verifier state and matched
verifier execution/result evidence. The standalone F0 receipt cannot prove that
its checkpoint reference resolves in the same session, that the tested hash
matches that checkpoint, or that ordering/execution correlation is valid; those
cross-record checks belong at a future evidence-set or journal integrity
boundary.

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

The provisional F0 manifest hashes deterministic canonical bytes containing Git
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
state A. F0.5 demonstrated this binding for one exact configured verifier in the
tested version/environment; production integrity enforcement remains
provisional.

Privacy exclusions override reconstruction completeness. An exclusion records a
capture gap and degrades completeness; no component may bypass it.

## Execution boundary

The v0 target is one instrumented Claude Code session in one isolated Git
worktree. Exact attribution under multiple sessions, human edits, or background
writers is unsupported. Background execution may be recorded as observed while
mutation attribution is explicitly degraded.

Current official Claude Code documentation lists relevant hook events and
fields, but their installed-version behavior, correlation, ordering, batching,
process model, concurrency, and fitness for checkpoint/verifier boundaries must
be validated in F0.5. Documentation availability is not an implementation or
fidelity guarantee.

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
