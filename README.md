# agent-context-runtime

This repository now has two explicit tracks. Planned Agent Forensics capabilities
must not be confused with the already implemented Context Optimization research
infrastructure.

## Active — Agent Forensics MVP validation

- **Active MVP hypothesis:** Agent Forensics
- **Status:** SELECTED FOR VALIDATION
- **Implementation:** F0 PROVISIONAL CONTRACTS / SYNTHETIC FIXTURE ONLY
- **Product validation:** NOT ESTABLISHED
- **Research novelty:** NOT ESTABLISHED
- **F0:** PASS
- **F0.5:** NOT STARTED

The provisional technical definition is **verification-bound project-state
incident reconstruction for coding agents**. The external demo narrative may be
**A Black Box for Coding Agents**.

The selected hypothesis is to observe one Claude Code session in one isolated
Git worktree, capture explicitly scoped repository-state evidence, bind explicit
verifier outcomes to tested pre-execution state, reconstruct an observed
pass-to-fail window, and eventually restore or fork the captured repository
scope. Provisional F0 schemas now exist for `AgentEvent`,
`WorkspaceCheckpoint`, `VerificationReceipt`, `IncidentReport`, and
`ForkReceipt`, together with a synthetic fixture. Real evidence capture,
checkpointing, verifier execution, analysis, the Incident Theater frontend, and
Workspace Fork remain unimplemented and unvalidated.

The next engineering gate after F0 is strictly:

> **F0.5 Reality Spike**

F0.5 must validate current Claude Code hook reality, event correlation and
process behavior, captured-scope restore fidelity, verifier pre-state binding,
Git base durability, journal concurrency, privacy gaps, and checkpoint overhead.
It has not started and requires separate authorization. No F1+ implementation
is authorized before F0.5 PASS.

See the active [`Agent Forensics MVP plan`](agent-forensics-mvp-plan.md),
[`current milestone`](docs/current-milestone.md),
[`MVP scope`](docs/mvp-scope.md), and
[`provisional architecture`](docs/architecture.md).

## Legacy — Context Optimization Research

The existing `acr` Python package is preserved as a real historical research
implementation. It provides evidence contracts, immutable content-addressed
storage, provenance/audit controls, a synchronous captured runtime, provider and
tool evidence, repository-state checks, isolated evaluation, noop A/A pairing,
accounting, and offline duplicate-read coverage analysis.

Historical status remains: M0 and M1 DONE; M2 runtime/provider/evaluator gates
PASS; one M3 noop A/A feasibility PASS while M3 overall is incomplete; Pre-M4
trust closure and execution/evaluator isolation PASS; the Multi-SWE-bench
offline duplicate-read coverage audit PASS with a formal intervention decision
of `NO_GO`. M4 never started, and no real request-deletion treatment was
implemented.

This track is frozen. Do not continue M4, provider request rewriting,
duplicate-read intervention, or Context Optimization policy work without
separate reauthorization. Its historical interpretation remains governed by
the legacy [`Context Optimization MVP plan`](agent-context-runtime-mvp-plan.md),
[`project status`](docs/project-status.md), and preserved receipts and coverage
artifacts.

Across both tracks, missing evidence stays unknown, content identity stays
separate from occurrence identity, and unsupported claims fail closed.
