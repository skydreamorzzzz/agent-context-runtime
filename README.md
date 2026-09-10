# agent-context-runtime

This repository now has two explicit tracks. Planned Agent Forensics capabilities
must not be confused with the already implemented Context Optimization research
infrastructure.

## Active — Agent Forensics MVP validation

- **Active MVP hypothesis:** Agent Forensics
- **Status:** SELECTED FOR VALIDATION
- **Implementation:** F0 CONTRACTS + DISPOSABLE F0.5 PROBES; PRODUCT NOT STARTED
- **Product validation:** NOT ESTABLISHED
- **Research novelty:** NOT ESTABLISHED
- **F0:** PASS
- **F0.5:** PASS
- **F1+:** NOT STARTED

The provisional technical definition is **verification-bound project-state
incident reconstruction for coding agents**. The external demo narrative may be
**A Black Box for Coding Agents**.

The selected hypothesis is to observe one Claude Code session in one isolated
Git worktree, capture explicitly scoped repository-state evidence, bind explicit
verifier outcomes to tested pre-execution state, reconstruct an observed
pass-to-fail window, and eventually restore or fork the captured repository
scope. Provisional F0 schemas now exist for `AgentEvent`,
`WorkspaceCheckpoint`, `VerificationReceipt`, `IncidentReport`, and
`ForkReceipt`, together with a synthetic fixture. Disposable F0.5 probes first
demonstrated the Claude incident and Git restore components independently. The
conditional closure then demonstrated one narrow integrated real path under
Claude Code 2.1.144 and Ubuntu/WSL2: exact `pytest -q` PASS pre-state, Claude
mutation, FAIL pre-state, restoration of that same passing captured state, and
manifest verification. This is probe evidence, not production implementation.

F0.5 is **PASS**. The closure also made executable state part of canonical
identity for every captured present regular file and verified restoration for
tracked and selected-untracked files. Claims remain limited to:

> **Captured repository scope in the tested version and environment.**

The Reality Spike leaves prompt-level correlation on the installed CLI,
background mutation attribution, shared-journal concurrency, Git GC durability,
and broader restore fidelity unsupported, degraded, or unknown. Real evidence
and exact boundaries are recorded in
[`docs/f0.5-reality-spike.md`](docs/f0.5-reality-spike.md). Production hook
capture, checkpoints, verifier integration, analysis, Incident Theater, and
Workspace Fork remain unimplemented. This was not a production Workspace Fork
or complete workspace restoration. F1+ is not authorized.

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
