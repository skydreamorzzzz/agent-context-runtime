# Current milestone: Forensics documentation baseline / F0 preparation

## Current state

```text
Strategy pivot: SELECTED
Documentation baseline: IN PROGRESS
Forensics implementation: NOT STARTED
F0: NOT STARTED
F0.5: NOT STARTED
```

Agent Forensics is selected for MVP validation, not approved as validated
architecture, product-market fit, or research novelty. This documentation pivot
changes active authority while preserving the Legacy Context Optimization
Research Track as historical fact.

The active authority is
[`agent-forensics-mvp-plan.md`](../agent-forensics-mvp-plan.md). The old
[`agent-context-runtime-mvp-plan.md`](../agent-context-runtime-mvp-plan.md)
remains authoritative only for interpreting the frozen Context Optimization
implementation and results.

## Work authorized by this milestone

- audit and align active documentation;
- preserve historical M0–M4 status, receipts, and coverage evidence;
- define tentative F0 evidence objects and a synthetic incident fixture scope;
- prepare explicit F0.5 questions and falsifiable checks;
- keep every Forensics schema, hook assumption, checkpoint rule, verifier
  binding, restore mechanism, and UI interface provisional.

## Not authorized

- Context Optimization M4, request deletion, provider request rewriting, or any
  duplicate-read intervention;
- F1 or later implementation;
- Claude Hooks, checkpoints, verifiers, restore, Workspace Fork, Git refs, file
  locks, or frontend code during this documentation pivot;
- claims of complete workspace/environment restoration, deterministic replay,
  causal RCA, validated architecture, product validation, or research novelty.

## Next engineering gate

> **F0 provisional contracts / fixture → F0.5 Reality Spike**

F0 defines only tentative evidence contracts and a synthetic incident fixture.
F0.5 tests those assumptions against current official Claude Code documentation
and real behavior, captured-scope repository round trips, verifier pre-state
binding, journal concurrency, Git durability, privacy gaps, and measured
checkpoint overhead. Only F0.5 PASS may freeze v0.1 contracts/policy and
authorize F1.

## Legacy gate disposition

The offline Multi-SWE-bench duplicate-read coverage audit passed with `NO_GO`
for the formal `omit_one_duplicate_read_v1` intervention. M4 never started, no
real request deletion treatment was implemented, and M4 is frozen rather than
being the current next gate.
