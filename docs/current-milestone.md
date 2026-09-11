# Current milestone: F1 Product Core Foundation

## Current state

```text
Documentation control-plane baseline: PASS
F0 provisional contracts / synthetic fixture: PASS
Pre-F0.5 integrity correction: PASS
F0.5 Reality Spike: PASS
F1 Product Core Foundation: PASS
F2 Failure Boundary: AUTHORIZED NEXT / NOT STARTED
Workspace Fork: NOT STARTED
Incident Theater: NOT STARTED
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

The production runtime now freezes only the v0.1 semantics used by `AgentEvent`,
`WorkspaceCheckpoint`, `VerificationReceipt`, `CapturedPathState`, capture scope,
and canonical captured-state identity. Historical F0 records remain readable as
provisional records. `IncidentReport` and `ForkReceipt` remain provisional.

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

## F1 Product Core Foundation evidence

- `acr claude` launches Claude Code with a temporary command-line `--settings`
  file. It does not write user, project, or local Claude settings.
- The Claude adapter persists stable events and excludes raw prompts, tool
  response/error bodies, environment values, and transcript paths.
- Exact configured verifier `PreToolUse` synchronously materializes a production
  checkpoint from Git base, tracked regular files, and selected non-ignored
  untracked regular files, including present/deleted content and executable
  state. Privacy exclusions and unsupported paths become explicit capture gaps.
- Exact verifier results require the same hashed Claude session and tool-use
  occurrence, and resolve a same-session pre-checkpoint with an identical tested
  manifest hash. Trusted PASS requires observed exit 0 and trusted FAIL requires
  an observed non-zero exit code. Unclassified failures and interruptions remain
  sanitized events without receipts; missing correlation emits no trusted receipt.
- Frozen capture is limited to the exactly validated Claude Code 2.1.144 on
  Ubuntu/WSL2 profile. Other versions or platform families block trusted capture.
- One corrected real production session recorded exact `pytest -q` PASS, an
  ordinary Claude Bash mutation of existing tracked `calculator.py`, and exact
  `pytest -q` exit-1 FAIL as two checkpoints and two receipts. It recorded no
  Edit/Write event. The evidence-set audit, privacy scan, and both independent
  manifest SHA256 recomputations passed. Evidence is committed at
  `docs/receipts/f1_product_core` and supersedes the prior unknown-exit smoke.
- Full local result: 166 tests PASS; Ruff PASS. Repository GitHub checks are
  reported separately because no repository workflow is assumed.

The Legacy Context Optimization M4 remains frozen. No duplicate-read candidate,
intervention, request deletion, or provider-rewriting work is authorized.

## Active engineering boundary

> **F1 Product Core Foundation is complete; the next gate is Failure Boundary**

Failure Boundary remains NOT STARTED and is authorized as the next gate.
Workspace Fork, Incident Theater, and frontend work remain NOT STARTED and
require separate authorization.
