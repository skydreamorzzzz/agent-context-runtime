# Current milestone: F0 and integrity correction complete / F0.5 preparation

## Current state

```text
Documentation control-plane baseline: PASS
F0 provisional contracts / synthetic fixture: PASS
Pre-F0.5 integrity correction: PASS
F0.5 implementation: NOT STARTED
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

Every Forensics field and nested helper remains:

> **PROVISIONAL UNTIL F0.5 PASS**

F0.5 must test the provisional model against official interface documentation
and real behavior, then revise or reject assumptions before any contract or
policy freezes. F0.5 is **NOT STARTED** and requires a separate explicit
instruction.

The Legacy Context Optimization M4 remains frozen. No duplicate-read candidate,
intervention, request deletion, or provider-rewriting work is authorized.

## Next engineering gate after this round

> **F0.5 Reality Spike**

Starting that gate requires a separate explicit instruction. F1 and later work
remain blocked until F0.5 PASS.
