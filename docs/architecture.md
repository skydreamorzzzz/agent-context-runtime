# Architecture and dependency boundaries

## Evidence flow

```text
raw blob -> normalize -> provenance + audit -> runtime events/request snapshots
        -> decision view -> candidate -> plan/receipt -> sealed run
        -> isolated evaluation + accounting -> reproducible report
```

`store` owns persistence mechanics only. `provenance` records input-to-output lineage. `audit` evaluates rule functions and never repairs evidence.

## Module ownership

| Area | Owns | Must not depend on |
|---|---|---|
| `contracts` | versioned schemas, `Fact`, labels | provider/runtime/evaluation |
| `visibility` | prefix, taint, scope checks and DecisionView projection | store/provider/evaluation |
| `state` | initial-tree and file-read bindings | candidate/evaluation |
| `candidates` | pure duplicate-read detection | store/provider/evaluation/I/O |
| `interventions` | one deterministic request edit and receipt validation | evaluator |
| `accounting` | raw usage normalization and price snapshots | candidate/evaluation |
| `evaluation` | sealed-artifact handoff to an isolated evaluator | runtime internals |
| `runtime` | synchronous agent/tool loop and raw capture | evaluator-private inputs |
| `experiment` | preflight and pair ordering | detection policy internals |
| `reporting` | read-only reconstruction from sealed evidence | runtime/provider calls |

Adapters translate external formats at the edge. They cannot contain policy decisions. `ports.py` is the only location for cross-boundary protocols.

## Data roots and trust domains

The `data-root` is external to an agent worktree and contains `blobs/`, `imports/`, `runs/`, `pairs/`, and `reports/`. `private_eval/` is host-only and must never be mounted, imported, or referenced by the online runtime. Runtime output is sealed before evaluation begins.

## Summary

Low coupling here means policy can be tested from constructed `DecisionView` objects, accounting can be recomputed without a live provider, and reports can be regenerated without executing an agent. Auditability comes from immutable raw references, explicit provenance, versioned contracts, and blocking findings that reports cannot suppress.
