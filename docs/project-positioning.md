# Project positioning

## Active positioning — Agent Forensics

The selected MVP hypothesis is **coding-agent incident forensics through
verification-bound project-state reconstruction**.

Provisional technical definition:

> **Verification-bound project-state incident reconstruction for coding agents.**

External demo narrative:

> **A Black Box for Coding Agents**

The intended product story is:

```text
Observe agent/tool execution
        ↓
Capture explicitly scoped repository-state evidence
        ↓
Bind explicit verifier results to tested pre-execution state
        ↓
Reconstruct Last Observed Passing State
        ↓
Failure Window
        ↓
First Observed Failing State
        ↓
Show recorded changes
        ↓
Restore / fork captured historical repository scope
```

This direction is **SELECTED FOR MVP VALIDATION**. F0.5 demonstrated one narrow
integrated Claude Code 2.1.144 and Git happy path with disposable probes,
including restoration of the incident's own passing captured state and
regular-file executable state. It did not validate the general architecture or
implement a product. Product validation and research novelty are not
established. Any later MVP implementation remains a separate decision—not a
market, novelty, causal, or complete-reconstruction claim.

## User value hypothesis

Coding-agent failures are often difficult to inspect because tool activity,
repository mutations, verifier outcomes, and recovery attempts are scattered
across transient interfaces and logs. The product hypothesis is that a developer
benefits from a trustworthy incident boundary:

- the last checkpoint at which a configured verifier was observed passing;
- the first checkpoint at which it was observed failing;
- the recorded mutation window between them;
- explicit capture gaps and unknowns;
- a verified fork of the captured last-observed-passing repository scope.

The terms deliberately remain **Last Observed Passing State**, **First Observed
Failing State**, and **Failure Window**. A passing configured verifier is not
global project goodness; temporal adjacency is not root cause.

## Product surface hypothesis

The planned **Incident Theater** is a first-class frontend organized around:

```text
PASS → FAILURE WINDOW → FAIL → RECOVERY ATTEMPTS
```

It may eventually show a timeline, checkpoints, tool events, verifier receipts,
state/file diffs, compaction observations, capture coverage, a replay slider,
and Workspace Fork action. It is not an analytics dashboard and is never
evidence authority. The backend establishes evidence; the frontend makes it
legible. The frontend consumes a stable derived `IncidentReport`/ViewModel and
must not convert heuristics into facts.

No frontend has been implemented. React, TypeScript, Vite, Tailwind, Framer
Motion, and a mature diff viewer are provisional technology choices, not current
repository capabilities.

## Trust and scope positioning

The differentiator being tested is not exhaustive telemetry. It is conservative
binding among:

```text
agent/tool occurrence
↕
captured repository-state evidence
↕
explicit verifier execution and result
↕
versioned derived incident view
```

The planned `captured_workspace_manifest_hash` covers only explicitly captured
repository scope. Privacy exclusions take precedence over reconstruction
completeness; exclusions and unsupported state become visible capture gaps.
Workspace Fork, if validated, may claim only captured-scope restoration and
manifest verification.

The MVP does not target complete environment or machine restore, process/network
reconstruction, deterministic LLM replay, exact model-state restoration, causal
root-cause attribution, LLM-generated RCA, or automatic remediation.

## Validation-first architecture

The detailed production design remains provisional after F0.5 PASS. Current
Claude Code official documentation is useful external evidence for documented
hook names and fields, while F0.5 supplies only the runtime observations
recorded for its tested version/environment. It does not generalize ordering,
batching, process, concurrency, overhead, or restore properties.

The validation order is intentionally:

```text
F0 tentative contracts and fixture
        ↓
F0.5 integrated real behavior + captured-scope round trip: PASS
        ↓
revise and freeze v0.1 contracts/policy
        ↓
F1+ product implementation
```

This prevents a provisional architecture from being mistaken for observed
reality.

## Legacy positioning — Context Optimization Research

This repository did not begin as an Agent Forensics project. It contains an
implemented **Legacy Context Optimization Research Track** built to measure
whether controlled context intervention could reduce end-to-end coding-agent
cost without silently sacrificing task quality.

That track established real evidence infrastructure, provenance and fail-closed
audit, captured runtime/provider behavior, workspace checks, evaluator
isolation, noop A/A feasibility, accounting, and offline duplicate-read coverage
analysis. Its actual status is:

- M0 DONE;
- M1 DONE;
- M2 runtime/provider/evaluator gates PASS;
- one M3 noop A/A feasibility PASS, while M3 overall remains incomplete;
- Pre-M4 trust closure PASS;
- execution/evaluator isolation PASS;
- Multi-SWE-bench offline duplicate-read coverage audit PASS;
- formal `omit_one_duplicate_read_v1` decision from that historical data: `NO_GO`;
- M4 NOT STARTED;
- no real request-deletion treatment implemented.

These results remain historical facts, including the negative coverage outcome.
The track is frozen, not erased or reframed as early Forensics work. Its plan,
receipts, coverage reports, and status retain historical authority. Candidate,
intervention, duplicate-read, DeepSeek experiment, provider-rewriting, and
Context Optimization policy modules are not the active product path.

## Completed F0.5 criteria

F0.5 established, within its declared and tested captured scope:

- the usable Claude hook surface and actual payload/process behavior;
- reliable or explicitly degraded event/tool correlation and ordering;
- verifier pre-state binding feasibility;
- capture → mutate → restore → identical captured-manifest round trip;
- explicit degradation/unknown boundaries for journal concurrency and sequence
  allocation;
- partial Git base durability feasibility with GC retention still unknown;
- privacy exclusions and their fidelity cost;
- acceptable measured checkpoint overhead.

F0.5 PASS permits a separately authorized next gate to revise and freeze
concrete v0.1 contracts and policy. It does not perform or authorize that work.
