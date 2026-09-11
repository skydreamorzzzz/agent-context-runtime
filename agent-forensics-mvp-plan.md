# Agent Forensics MVP Validation Plan

> **STATUS: ACTIVE MVP VALIDATION BASELINE**
>
> This document is the active implementation authority for current development.
> It records a selected hypothesis, provisional architecture, bounded scope, and
> validation gates. Except for the explicitly recorded completed gate status,
> it does not describe implemented operational capabilities, validated
> architecture, established product demand, research novelty, or causal truth.
>
> The historical Context Optimization implementation remains governed by
> [`agent-context-runtime-mvp-plan.md`](agent-context-runtime-mvp-plan.md),
> historical status, receipts, and coverage artifacts. That legacy track is
> frozen; M4 and duplicate-read intervention work are not authorized.

## 1. Selected hypothesis and claim boundary

- **Active MVP hypothesis:** Agent Forensics
- **Status:** SELECTED FOR MVP VALIDATION
- **Implementation:** F1 PRODUCT CORE FOUNDATION — REAL CAPTURE + VERIFIED STATE
- **Product validation:** NOT ESTABLISHED
- **Research novelty:** NOT ESTABLISHED
- **F0:** PASS
- **Pre-F0.5 integrity correction:** PASS
- **F0.5:** PASS
- **F1 Product Core Foundation:** PASS
- **F2 Failure Boundary:** AUTHORIZED NEXT / NOT STARTED

Provisional technical definition:

> **Verification-bound project-state incident reconstruction for coding agents.**

External demo narrative:

> **A Black Box for Coding Agents**

Target narrative:

> Reconstruct the failure boundary. Show exactly what changed in captured
> repository scope. Fork the captured last-observed-passing repository state.

These are project narrative and implementation hypotheses. They are not novelty,
causal, fidelity, correctness, or market claims.

The proposed flow is:

```text
Observe agent/tool execution
        ↓
Capture repository-state evidence
        ↓
Bind explicit verifier results to tested state
        ↓
Reconstruct:
Last Observed Passing State
        ↓
Failure Window
        ↓
First Observed Failing State
        ↓
Show recorded changes
        ↓
Restore / fork captured historical repository state
```

Only **Last Observed Passing State**, **First Observed Failing State**, and
**Failure Window** are permitted terms. “Last Good State,” “First Bad State,”
global project correctness, root cause, and causal attribution exceed the
evidence model.

## 2. v0.1 validation scope

The provisional execution contract is:

```text
ONE user
ONE Claude Code session
ONE isolated Git worktree
ONE local repository
ONE or more explicitly configured verifiers
LOCAL evidence store
LOCAL frontend
```

Planned v0.1 support, contingent on the gates below:

- Claude Code only;
- Linux / WSL first;
- a normal local Git repository;
- tracked regular files and deletions;
- dirty working-tree state;
- selected, non-ignored untracked files;
- explicit shell verifiers;
- local content-addressed evidence;
- historical forensic replay;
- Git-worktree-based Workspace Fork;
- local Incident Theater frontend.

Explicitly out of scope:

- Codex, Cursor, Gemini, OpenCode, multi-provider, or generic agent support;
- multi-user, team, cloud backend, or enterprise authentication;
- exact outbound model context or internal model state;
- complete environment, machine, shell-session, process, network, or database snapshots;
- environment resurrection or running-process reconstruction;
- deterministic LLM replay or exact trajectory continuation;
- causal root-cause attribution, causal probability, or LLM-generated RCA;
- automatic remediation;
- project-wide cross-session lineage;
- a generic observability platform.

Concurrent modification by multiple Claude sessions, a human editor, or
background writers in one instrumented worktree is unsupported. If background
execution is observed, the maximum permitted claim is:

> background execution observed; exact mutation attribution may be degraded.

Do not claim external mutation detection unless it is separately implemented
and validated.

## 3. Epistemic and privacy invariants

The following legacy ACR disciplines are inherited:

- a content hash identifies bytes, not occurrences;
- occurrence, event, and source-location identity are separate from content identity;
- `unknown`, `false`, zero, empty, and `not_applicable` remain distinct;
- missing evidence is not inferred;
- Observed, Derived, Estimated, and Unknown are distinct statuses;
- evidence is immutable and raw bytes are content-addressed;
- unsupported claims fail closed;
- malformed or inconsistent evidence produces deterministic BLOCK findings;
- source manifests and producer manifests remain separate;
- persistent top-level records follow the existing `Envelope` convention and reuse `acr.contracts.Provenance` unless a post-spike revision explicitly replaces them.

Context-optimization objects such as `Candidate`, `Intervention`, `DecisionView`,
and duplicate-read-specific structures are not carried into the Forensics MVP
merely for code reuse.

### Privacy takes precedence

> **Privacy constraints take precedence over reconstruction completeness.**

The future capture path must follow:

```text
exclude sensitive artifact
        ↓
record capture gap
        ↓
degrade capture completeness
```

It must never silently capture an excluded artifact to improve fidelity.
Checkpoint and incident analysis may remain useful with gaps, but missing state
must not be inferred and a fork may verify only captured scope.

The v0 design must account for:

- `.acrignore`;
- sensitive default-deny patterns;
- per-blob size caps;
- stdout/stderr size caps with explicit truncation status;
- no full prompt capture by default;
- no environment-variable values;
- no proactive `.env` reads;
- no credential, token, or private-key contents.

This MVP does not require a complex redaction engine.

## 4. Provisional evidence model

All objects and fields in this section originated as **PROVISIONAL until F0.5
PASS**. F0.5 is now PASS, which permits a separately authorized revision/freeze
gate; it does not itself freeze repository contracts. The F0 Python shapes,
synthetic fixture, and disposable closure evidence do not make them production
contracts.

Primary append-only evidence:

```text
AgentEvent
WorkspaceCheckpoint
VerificationReceipt
```

Derived view:

```text
IncidentReport
```

Action receipt:

```text
ForkReceipt
```

`AgentEvent`, `WorkspaceCheckpoint`, and `VerificationReceipt` are evidence.
`IncidentReport` is an analyzer-version-dependent derived view that can be
recomputed. `ForkReceipt` records a restore/fork action and its verification; it
does not upgrade source evidence or fill capture gaps.

### 4.1 AgentEvent

Proposed adapter boundary:

```text
Claude hook payload
        ↓
Claude-specific adapter
        ↓
AgentEvent
```

The analyzer, frontend, and future derived views must not directly depend on a
raw Claude payload. Event fields, ordering evidence, correlation rules, and the
adapter contract remain provisional.

### 4.2 WorkspaceCheckpoint

Use `captured_workspace_manifest_hash`, not `workspace_hash`. If an abbreviated
`workspace_manifest_hash` is later selected, it must retain this definition:

> This hashes only the explicitly captured repository scope. It does not
> represent complete repository, environment, process, or machine state.

The F0 canonical captured-state manifest separates state identity from
checkpoint occurrence identity. Its deterministic bytes contain only:

```text
provisional manifest format
Git base identity
canonical path-ordered captured overlay:
  repository-relative path
  tracked / selected-untracked classification
  present / deleted state
  content hash when present
  executable boolean when present regular file
```

Executable is `true` or `false` for every captured present regular file,
whether tracked or selected-untracked, and `null`/not applicable for deleted
paths. It is not a generic POSIX permission model.

Checkpoint ID, session ID, ordering, timestamp, trigger, event ID, evidence
locator, and incident metadata are excluded. Consequently, two checkpoint
records may be distinct occurrences while sharing one
`captured_workspace_manifest_hash` when their Git base and captured overlay are
identical. Different Git bases or captured overlays produce different state
identities. The F0.5 closure demonstrated this identity and restore behavior in
the narrow tested environment, including executable state, but the
representation remains provisional until separately frozen.

`WorkspaceCheckpoint` validation recomputes the canonical captured-state hash
from `git_base` and `captured_paths`. Both
`captured_workspace_manifest_hash` and `manifest_ref.blob_hash` must equal that
recomputed value; agreement between the two stored fields alone is
insufficient.

Tentative fields:

```text
checkpoint_id
session_id
ordering evidence
timestamp

git_head
captured_workspace_manifest_hash

modified tracked paths
deleted tracked paths
selected untracked paths

content-addressed blob references

capture_scope
capture_completeness
trigger evidence
```

Tentative restoration model:

```text
Git base commit
+
captured working-tree overlay
=
captured repository scope
```

This is not a claim of complete workspace or machine state.

### 4.3 Capture scope

Every checkpoint must say what was and was not captured. The design must be able
to distinguish at least:

```text
capture_scope:
  tracked_regular_files
  selected_untracked_files
  ignored_files
  environment
  running_processes
  database
  network
```

Unsupported, excluded, or unobserved areas must remain explicit, for example:

```text
Repository evidence: captured
Ignored artifacts: not captured
Environment: not captured
Process state: not captured
```

`capture_completeness` is relative to declared captured scope and policy. It
must degrade when privacy policy, size caps, unsupported file types, or capture
failures create gaps.

### 4.4 VerificationReceipt

The correctness target is pre-state binding:

```text
pre-verifier captured repository state A
        ↓
execute verifier
        ↓
record result
        ↓
optional post state B
```

A post-verifier checkpoint cannot be used as if it were the tested state,
because the verifier itself may mutate files.

Tentative receipt fields:

```text
verifier_spec_hash
pre_checkpoint_id
tested_captured_workspace_manifest_hash
command
cwd
started_at
finished_at
exit_code
result
stdout_ref
stderr_ref
post_checkpoint_id optional
```

The maximum intended meaning is:

> The verifier was observed executing against the captured pre-execution
> repository state.

It does not mean that the project was globally good, correct, or complete.

For the frozen F1 runtime slice, trusted `passed=true` is equivalent to an
observed exit code of zero and trusted `passed=false` is equivalent to an
observed non-zero exit code. A `PostToolUseFailure` without strict stable
exit-code evidence remains a sanitized terminal event and does not produce a
trusted receipt.

Verifiers are explicitly user-configured. A standalone, strictly matched
invocation such as `pytest -q` may become receipt-eligible. A compound command
such as `sed -i ... && pytest -q` must not be promoted to equally reliable
verification through speculative shell-semantic parsing. If strict binding
cannot be established, verification is UNKNOWN. F0.5 demonstrated this model
for one exact configured command in its tested version/environment; other
command forms and environments do not inherit that result.

The standalone F0 `VerificationReceipt` cannot establish cross-record
integrity. At a future evidence-set or journal integrity boundary,
`pre_checkpoint_id` must resolve to a checkpoint in the same session, the
receipt's tested manifest hash must equal that checkpoint's manifest hash, and
ordering/execution correlation must be valid. The runtime evidence structure
needed to enforce those relations remains a later production-integrity concern.

### 4.5 IncidentReport

Tentative fields:

```text
last_observed_passing_checkpoint
first_observed_failing_checkpoint
failure_window
mutations_inside_window
verification history
recovery attempts
compaction observations
capture gaps
unknown notes
analyzer_version
```

The view excludes `root cause`, `caused_by`, and `causal_probability`.

### 4.6 ForkReceipt

Tentative future behavior:

```text
historical checkpoint
        ↓
resolve or pin Git base
        ↓
create isolated worktree
        ↓
restore captured overlay
        ↓
recompute captured_workspace_manifest_hash
        ↓
verify captured scope
        ↓
emit ForkReceipt
```

The only intended success claim is:

> captured repository scope restored and manifest-verified.

Workspace Fork is not a model-state fork, deterministic replay, trajectory
continuation, exact parallel universe, or complete workspace restore. v0 does
not need to start Claude automatically; a future CLI may print the restored path
and an explicit continuation command.

## 5. Provisional capture and checkpoint policy

Event occurrence and checkpoint materialization are distinct. The current policy
hypothesis is:

```text
Read / Grep / Glob
→ event only

Edit / Write
→ mutation checkpoint candidate

Bash
→ conservatively mutation-capable

Verifier
→ forced pre-state capture
→ optional post-state capture
```

Current official Claude Code documentation lists `PreToolUse`, `PostToolUse`,
and `PostToolBatch`, and describes `PostToolBatch` as firing after a parallel
tool-call batch resolves and before the next model call. F0.5 observed these
events on installed Claude Code 2.1.144, including a batch containing two Read
calls, but did not establish `PostToolBatch` as a safe checkpoint boundary.
The concrete production policy remains provisional.

Every-event repository scanning is not required. F0.5 measured 2.949–7.311 ms
for four captures in the small fixture; this is characterization, not a frozen
policy or a general performance guarantee.

## 6. External-interface baseline and Reality Spike assumptions

Official Claude Code documentation reviewed on 2026-09-10:

- [Hooks reference](https://code.claude.com/docs/en/hooks)
- [Hooks guide](https://code.claude.com/docs/en/hooks-guide)

The current reference documents lifecycle events including `PreToolUse`,
`PostToolUse`, `PostToolUseFailure`, `PostToolBatch`, compaction events, and
worktree events; common inputs including `session_id`, `cwd`, and hook event
name; tool inputs/outputs and `tool_use_id` on applicable events; and background
or async-related fields/behavior. These are version-sensitive external
documentation facts only.

F0.5 established only the following narrow observations on Claude Code 2.1.144:

- relevant session, tool pre/post/failure, batch, and stop events were emitted;
- `tool_use_id` correlated the tested pre/post outcomes;
- exact `pytest -q` matching allowed synchronous pre-state capture before two
  independently marked verifier starts;
- one parallel-read batch was grouped, but general hook concurrency was not
  established;
- background Bash completion/mutation attribution was degraded.

The following remain unverified, version-sensitive, degraded, or unknown:

- session identity across start, resume, compact, and any fork-like lifecycle;
- prompt-level correlation (`prompt_id` was absent on installed 2.1.144);
- general event ordering and hook scheduling across parallel calls;
- subagent, compaction, resume, and fork-like lifecycle behavior;
- stable background completion and exact mutation attribution;
- how command hooks overlap and whether concurrent journal writes occur;
- production sequence allocation and shared-journal safety.

Documentation is not substituted for a real spike where runtime behavior,
performance, durability, or cross-event correlation is the question. Any
unverified or contradictory detail remains an **F0.5 external-interface
assumption**. See [`docs/f0.5-reality-spike.md`](docs/f0.5-reality-spike.md).

### Journal concurrency

The legacy `append_run_jsonl()` came from a controlled synchronous runtime. It
is not evidence that multiple hook processes can safely share unlocked append
and sequence allocation. A Linux/WSL per-session file lock is only a candidate
design. The probe avoided shared append by writing one immutable file per hook
invocation. Multiple PIDs were observed, but shared-write safety, lock need, and
sequence allocation remain unknown.

### Git historical-state durability

Persisting only `git_head` may be insufficient after reset, rebase, ref movement,
or garbage collection. An internal Git ref such as a future `refs/acr/...` is a
candidate base-pinning mechanism, not a frozen name or validated design. A
disposable ref retained its base across branch movement, but garbage-collection
retention, cleanup, and worktree compatibility remain unknown.

## 7. Incident Theater

Incident Theater is a first-class planned product surface, not an analytics
dashboard and not evidence authority. Its central visual narrative is:

```text
PASS
 ↓
FAILURE WINDOW
 ↓
FAIL
 ↓
RECOVERY ATTEMPTS
```

Planned views include timeline, checkpoints, tool events, verification receipts,
state/file diff, compaction markers, capture coverage, replay slider, and Fork
action. A provisional implementation stack may be React, TypeScript, Vite,
Tailwind, Framer Motion, and a mature diff component.

No `web/` directory is authorized during this documentation pivot. F1 may begin
only after F0.5 PASS. The frontend must consume an `IncidentReport` or stable
ViewModel, never raw Claude payloads. It cannot generate evidence, modify
evidence truth, hide capture gaps, or present heuristic visualization as fact.

> Backend makes the evidence trustworthy. Frontend makes the evidence legible
> and compelling.

## 8. Legacy asset disposition

Reuse or refactor candidates, only when an active gate authorizes code changes:

- `contracts.py`: `ContractModel`, `EvidenceRef`, `Fact/status`, versioned serialization, and occurrence/content identity concepts;
- `store.py`: SHA256 content-addressed blobs, immutable write-once behavior, and evidence references; hook multi-process safety is unvalidated;
- `state.py`: workspace path safety and deterministic manifest/hash ideas; the initial-tree full scan is not a dynamic checkpoint implementation;
- `experiment.py` and `evaluation.py`: retained controlled counterfactual research/lab assets, outside the active v0 product path.

Frozen, preserved, and not actively extended:

- `audit.py` and legacy audit rules;
- `candidates.py` and the duplicate-read detector;
- interventions and provider request rewriting;
- the DeepSeek active experiment path;
- M4 context deletion and Context Optimization policies.

Do not delete or broadly move these assets. Do not create future feature stubs,
registries, DI systems, plugin frameworks, event buses, or causal DAGs.

## 9. Milestones and gates

Forensics milestones use `F0`, `F0.5`, `F1`, and later identifiers. Legacy
Context Optimization `M0`–`M4` identifiers keep their historical meanings and
must not be reused.

### F0 — Provisional Forensics contracts / fixture

**Status: PASS.** The five provisional records and a synthetic incident fixture
are implemented and contract-tested. This status does not freeze the schemas or
validate any external or operational assumption.

Goals:

- define the smallest tentative evidence schema;
- establish a synthetic incident fixture;
- define the `IncidentReport` view model;
- label every F0 contract provisional pending reality validation.

F0 does not freeze schemas and does not establish hook, checkpoint, verifier,
restore, fork, or product feasibility.

### F0.5 — Reality Spike

This is the controlling gate before formal backend or UI development.

When separately authorized, F0.5 permits only the minimum experimental probe
code required to test real Claude interface behavior, captured-scope repository
round trips, verifier binding, journal concurrency, checkpoint overhead, and
Git durability. Probe code:

- does not define a public or product API;
- must not silently become production implementation;
- must not trigger F1 or later scope;
- may produce observations and measurements that inform later production design;
- does not make its experimental architecture the production architecture.

Where practical, probe code should remain isolated from the active production
module surface. The completed probe remains experimental and does not define
the production module surface.

#### Claude interface reality

Verify official documentation against real execution for hook availability,
payloads, session identity, tool correlation, event ordering, batching, process
behavior, Bash mutation observation, background behavior, and verifier matching.

#### Captured-scope repository round trip

Verify:

```text
capture
→ mutate
→ restore
→ captured manifest hash identical
```

This verifies captured scope only, not complete repository, environment, or
machine state.

#### Verifier binding

Verify whether the interface can reliably associate:

```text
pre-state capture
→ verifier execution
→ result
→ optional post-state
```

#### Operational sanity

Measure checkpoint overhead, hook write concurrency, sequence allocation, Git
base-pinning feasibility, restore fidelity within captured scope, and the effect
of privacy exclusions and size caps on completeness.

#### F0.5 exit

Only after F0.5 PASS and separate implementation authorization may the project:

1. revise provisional contracts according to observed reality;
2. freeze v0.1 evidence contracts;
3. freeze a concrete checkpoint policy;
4. freeze verifier-binding semantics;
5. authorize F1.

Contradictions are evidence. Record them and revise the design; do not fabricate
agreement or silently force the provisional architecture.

### Roadmap correction after F0.5

The original roadmap ordered Incident Theater on the fixture before real event
capture, repository checkpoints, verifier binding, historical replay, and
Workspace Fork. That ordering remains part of the planning history, but F0.5
showed that the product core should be established before presentation work.
The active implementation order is now:

```text
production real capture
→ verified repository state
→ failure-window derivation
→ real Workspace Fork
→ minimal product ViewModel / CLI
→ Incident Theater
→ polish
```

### F1 — Product Core Foundation

Capture a real Claude Code session into sanitized `AgentEvent` evidence and bind
an exact configured verifier result to a production pre-execution
`WorkspaceCheckpoint`. Freeze only the v0.1 contract and capture semantics used
by this runtime slice. Do not productize Failure Window, Workspace Fork, or UI.

### F2 — Failure Boundary

Derive Last Observed Passing State, First Observed Failing State, and Failure
Window from production evidence without causal claims.

### F3 — Workspace Fork

Restore and manifest-verify captured historical repository scope, then emit a
`ForkReceipt`.

### F4 — Minimal product ViewModel / CLI

Expose stable evidence-derived session and failure-boundary views without
making the frontend an evidence authority.

### F5 — Incident Theater

Build the minimal incident experience on real production evidence rather than
the synthetic fixture.

### F6 — Controlled 60-second demo and polish

Demonstrate:

```text
Observed Pass
↓
real mutation
↓
Observed Fail
↓
failure-window reconstruction
↓
recovery attempts
↓
historical evidence replay
↓
fork captured last-observed-passing repository state
```

## 10. Current authorization

F0 provisional contracts and the synthetic fixture are complete. The
Pre-F0.5 integrity correction is PASS. F0.5 is PASS after its accepted
conditional closure demonstrated one narrow integrated real path: an exact
verifier-bound PASS captured state, a Claude mutation, a verifier-bound FAIL
captured state, and restoration/manifest verification of that same passing
state. Canonical state identity and disposable restoration also cover the
executable boolean for captured present regular files, tracked and
selected-untracked. This evidence did not itself authorize production hooks,
production checkpoints, verifier integration, Workspace Fork, a production
analyzer, or frontend work. Separate authorization on 2026-09-11 started F1
Product Core Foundation, limited to real session capture plus verified
repository state. F1 is PASS after the committed production smoke recorded
below.

The completed reality gate is:

> **F0.5 Reality Spike — PASS**

F0.5 probe observations and verdict are recorded in
[`docs/f0.5-reality-spike.md`](docs/f0.5-reality-spike.md). The corrected F1 gate
authorizes Failure Boundary as the next gate, but it remains NOT STARTED. F1 does
not authorize Workspace Fork, Incident Theater, M4, or duplicate-read
intervention work.

The corrected F1 production smoke evidence is recorded under
[`docs/receipts/f1_product_core`](docs/receipts/f1_product_core). One real Claude
Code 2.1.144 session on Ubuntu/WSL2 produced sanitized events, an exact
`pytest -q` PASS receipt with observed exit 0, an ordinary Bash mutation of an
existing tracked file, and an exact-`pytest -q` FAIL receipt with observed exit 1. No
Edit/Write event was recorded. Both receipts resolve to same-session production
checkpoints whose distinct canonical manifest bytes recompute to their recorded
hashes. This supersedes the prior smoke whose failure exit code was unknown and
establishes the corrected F1 implementation capability only; product validation
remains NOT ESTABLISHED. Failure Boundary remains NOT STARTED.
