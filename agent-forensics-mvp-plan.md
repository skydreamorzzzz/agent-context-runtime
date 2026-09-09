# Agent Forensics MVP Validation Plan

> **STATUS: ACTIVE MVP VALIDATION BASELINE**
>
> This document is the active implementation authority for current development.
> It records a selected hypothesis, provisional architecture, bounded scope, and
> validation gates. It does not describe implemented capabilities, validated
> architecture, established product demand, research novelty, or causal truth.
>
> The historical Context Optimization implementation remains governed by
> [`agent-context-runtime-mvp-plan.md`](agent-context-runtime-mvp-plan.md),
> historical status, receipts, and coverage artifacts. That legacy track is
> frozen; M4 and duplicate-read intervention work are not authorized.

## 1. Selected hypothesis and claim boundary

- **Active MVP hypothesis:** Agent Forensics
- **Status:** SELECTED FOR MVP VALIDATION
- **Implementation:** NOT STARTED
- **Product validation:** NOT ESTABLISHED
- **Research novelty:** NOT ESTABLISHED

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

All objects and fields in this section are **PROVISIONAL until F0.5 PASS**. They
must not be described as frozen repository contracts or added to the current
Python contracts during this documentation pivot.

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

Verifiers are explicitly user-configured. A standalone, strictly matched
invocation such as `pytest -q` may become receipt-eligible. A compound command
such as `sed -i ... && pytest -q` must not be promoted to equally reliable
verification through speculative shell-semantic parsing. If strict binding
cannot be established, verification is UNKNOWN. F0.5 must determine whether
actual hook boundaries can support this model.

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
tool-call batch resolves and before the next model call. This is an external
documentation observation, not a repository guarantee or proof that it is a
safe checkpoint boundary. The concrete policy, including whether
`PostToolBatch` is a useful checkpoint opportunity or synchronization boundary,
must be decided from F0.5 observations.

Every-event repository scanning is not required. F0.5 must measure checkpoint
overhead before a policy freezes.

## 6. External-interface baseline and Reality Spike assumptions

Official Claude Code documentation reviewed on 2026-09-09:

- [Hooks reference](https://code.claude.com/docs/en/hooks)
- [Hooks guide](https://code.claude.com/docs/en/hooks-guide)

The current reference documents lifecycle events including `PreToolUse`,
`PostToolUse`, `PostToolUseFailure`, `PostToolBatch`, compaction events, and
worktree events; common inputs including `session_id`, `cwd`, and hook event
name; tool inputs/outputs and `tool_use_id` on applicable events; and background
or async-related fields/behavior. These are version-sensitive external
documentation facts only.

The repository has not established the semantics it needs. F0.5 must validate:

- actual hook availability in the selected installed Claude Code version;
- real payloads and optional/missing fields;
- session identity across start, resume, compact, and any fork-like lifecycle;
- tool-call correlation across pre, success, failure, and batch events;
- event ordering and batch composition under sequential and parallel calls;
- hook process lifecycle and working-directory behavior;
- background Bash/subagent observations and attribution limits;
- whether verifier matching can be strict and pre-state-bound;
- how command hooks overlap and whether concurrent journal writes occur;
- sequence allocation under the observed process model.

Documentation is not substituted for a real spike where runtime behavior,
performance, durability, or cross-event correlation is the question. Any
unverified or contradictory detail remains an **F0.5 external-interface
assumption**.

### Journal concurrency

The legacy `append_run_jsonl()` came from a controlled synchronous runtime. It
is not evidence that multiple hook processes can safely share unlocked append
and sequence allocation. A Linux/WSL per-session file lock is only a candidate
design. F0.5 must observe process behavior, concurrent writes, session identity,
correlation, ordering, and sequence allocation before selecting a mechanism.

### Git historical-state durability

Persisting only `git_head` may be insufficient after reset, rebase, ref movement,
or garbage collection. An internal Git ref such as a future `refs/acr/...` is a
candidate base-pinning mechanism, not a frozen name or validated design. F0.5
must test base resolution, retention, cleanup, and worktree compatibility.

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

Goals:

- define the smallest tentative evidence schema;
- establish a synthetic incident fixture;
- define the `IncidentReport` view model;
- label every contract provisional pending F0.5.

F0 does not freeze schemas and does not establish hook, checkpoint, verifier,
restore, fork, or product feasibility.

### F0.5 — Reality Spike

This is the controlling gate before formal backend or UI development.

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

Only after F0.5 PASS may the project:

1. revise provisional contracts according to observed reality;
2. freeze v0.1 evidence contracts;
3. freeze a concrete checkpoint policy;
4. freeze verifier-binding semantics;
5. authorize F1.

Contradictions are evidence. Record them and revise the design; do not fabricate
agreement or silently force the provisional architecture.

### F1 — Incident Theater on fixture

After F0.5 PASS, implement the incident view against the revised fixture and
stable view model.

### F2 — Real event capture

Capture validated Claude hook inputs into the `AgentEvent` journal.

### F3 — Real repository checkpoints

Materialize mutation-bound captured repository-state evidence under the frozen
scope and policy.

### F4 — Verification / Failure Window

Produce pre-state-bound `VerificationReceipt` evidence and deterministic,
versioned `IncidentReport` derivation.

### F5 — Historical replay UI

Drive timeline, diff, capture coverage, and replay from real evidence.

### F6 — Workspace Fork

Restore and manifest-verify captured historical repository scope, then emit a
`ForkReceipt`.

### F7 — Controlled 60-second demo

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

The documentation control-plane pivot is the only work authorized in the
current round. Do not modify implementation code or tests, create a frontend,
install dependencies, or implement hooks, checkpoints, verifiers, restore,
forks, Git refs, or file locks.

After this documentation baseline is accepted, the only next engineering gate
is:

> **F0 provisional contracts / fixture → F0.5 Reality Spike**

Nothing in this plan authorizes M4 or duplicate-read intervention work.
