# Current milestone: F0.5 complete / next-gate authorization pending

## Current state

```text
Documentation control-plane baseline: PASS
F0 provisional contracts / synthetic fixture: PASS
Pre-F0.5 integrity correction: PASS
F0.5 Reality Spike: PASS
F1+: NOT STARTED
```

F0 makes the Agent Forensics hypothesis concrete enough to test. It does not
freeze or validate the design.

## F0 evidence of completion

- `src/acr/forensics_contracts.py` defines provisional `AgentEvent`,
  `WorkspaceCheckpoint`, `VerificationReceipt`, `IncidentReport`, and
  `ForkReceipt` models, isolated from legacy Context Optimization contracts.
- `tests/fixtures/forensics/f0_synthetic_incident.json` records a synthetic-only
  pass-to-fail incident, two recovery observations, an explicit privacy capture
  gap, an expected derived report, and an unexecuted schema-only fork receipt.
- `tests/test_forensics_contracts.py` verifies round trips, explicit unknown
  semantics, captured-scope limits, pre-checkpoint verifier binding, derived-view
  identity, non-causal fields, content-addressed fixture integrity, and fork
  claim limits.
- Full repository result at F0 completion: 134 tests PASS; Ruff PASS.

These are synthetic contract checks. No evidence was captured from Claude Code,
no verifier command was executed by the Forensics implementation, and no
workspace was checkpointed, restored, or forked.

## Pre-F0.5 integrity correction

- The canonical captured-state manifest now contains Git base identity plus a
  deterministic path-ordered captured overlay, without checkpoint occurrence
  metadata.
- `WorkspaceCheckpoint` recomputes the canonical state hash from Git base and
  captured paths; both stored manifest hash fields must equal it.
- Distinct checkpoint occurrences may share captured-state identity; changing
  the Git base changes that identity.
- `IncidentReport.capture_gaps` accepts only uncaptured or explicitly unknown
  scope entries.
- The active architecture now separates the event journal, checkpoints,
  verification receipts, derived report, and checkpoint-authorized fork path.
- Recorded full local repository result after the correction: 141 tests PASS;
  Ruff PASS.

This correction strengthens only F0 internal semantic consistency. It adds no
Claude interface, checkpoint capture, verifier correlation, restore, journal,
Git durability, performance, or product feasibility evidence.

## Gate boundary

Every Forensics field and nested helper remains provisional. The Reality Spike
established only a narrow tested path, not a frozen general contract or product
implementation.

The accepted conditional closure used one Claude Code 2.1.144 session and one
disposable repository to demonstrate exact-`pytest -q` PASS state capture,
Claude mutation, FAIL state capture, restoration of that same passing captured
state, and manifest verification. It also added executable state to canonical
identity for captured present regular files and verified restore in both
directions for tracked and selected-untracked paths.

Other unsupported, degraded, and unknown boundaries remain recorded in
[`f0.5-reality-spike.md`](f0.5-reality-spike.md). The integrated result claims
captured repository scope only in the tested version/environment. It is not a
production Workspace Fork, complete workspace restoration, or causal analysis.

Recorded final local conditional-closure result: 151 tests PASS; Ruff PASS.
This is local test evidence, not a GitHub CI result.

The Legacy Context Optimization M4 remains frozen. No duplicate-read candidate,
intervention, request deletion, or provider-rewriting work is authorized.

## Active engineering boundary

> **F0.5 is complete; await separate authorization for the next MVP implementation gate**

Do not continue probe expansion or begin F1 in the absence of a separate
instruction.
