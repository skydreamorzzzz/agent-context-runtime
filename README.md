# agent-context-runtime

`acr` is the MVP scaffold for an auditable, cost-aware context-management runtime.

The repository is intentionally organized around evidence boundaries rather than a framework hierarchy:

- `src/acr/` contains pure contracts and runtime-facing modules.
- `data/` is a user-supplied evidence root selected with `--data-root`; it is ignored by Git.
- `private_eval/` is deliberately separate from runtime code and data.
- `docs/architecture.md` records allowed dependencies and the audit trail.

## Summary

The MVP performs clean, from-scratch baseline/treatment pairs. It may omit one verified old duplicate `read_file` result from one outbound request. Every conclusion must be reconstructible from raw blobs, normalized records, provenance, audit findings, sealed runs, evaluation results, and the cost ledger. Missing evidence remains `unknown`; it is never inferred.

Implementation status: M0/M1 are complete. M2 has real provider capture and an
independent evaluator; the current gate closes the bounded model-directed
read/write/test loop, reconstructible sealed submission, and persisted usage
ledger before any context intervention. Real runtime evidence remains local.

See [the architecture guide](docs/architecture.md), [audit checklist](docs/audit-checklist.md), and the frozen [MVP plan](agent-context-runtime-mvp-plan.md).
