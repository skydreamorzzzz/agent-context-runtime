# Agent Forensics v0.1 validation scope

> **Status:** F0 PASS; F0.5 PASS for one narrow integrated disposable-probe
> path; F1+ NOT STARTED. Operational product capabilities are not implemented.
> The active authority is
> [`agent-forensics-mvp-plan.md`](../agent-forensics-mvp-plan.md).

## Target boundary

```text
ONE user
ONE Claude Code session
ONE isolated Git worktree
ONE local repository
ONE or more explicitly configured verifiers
LOCAL evidence store
LOCAL frontend
```

Planned scope after the narrow F0.5 PASS: Claude Code only; Linux/WSL first;
normal local Git repositories; tracked regular files and deletions; dirty tree
state; executable boolean for captured present regular files; selected
non-ignored untracked files; explicit shell verifiers; local
content-addressed evidence; historical forensic replay; captured-scope,
Git-worktree-based Workspace Fork; and a local Incident Theater.

All production checkpoint, verifier, restore, fork, hook, analyzer, and frontend
details remain provisional. F0.5 demonstrated one integrated disposable-probe
path, not operational product capabilities.

## State claim boundary

The planned state hash is `captured_workspace_manifest_hash`. It covers only
explicitly captured repository scope. Privacy exclusions, unsupported file
types, size limits, and capture failures are recorded as gaps and reduce
completeness. Privacy takes precedence over reconstruction completeness.

A future successful fork may claim only that captured repository scope was
restored and manifest-verified. It may not claim complete workspace, machine,
environment, process, database, network, or model-state restoration.

## Out of scope

- other coding-agent providers, multiple providers, users, or teams;
- cloud backend, enterprise auth, database/dashboard infrastructure, or generic observability;
- concurrent precise attribution across sessions, humans, and background writers;
- exact outbound model context or full prompt capture by default;
- full environment snapshots or environment resurrection;
- running-process, network, database, shell-session, or machine reconstruction;
- deterministic LLM replay, exact model-state restore, or trajectory continuation;
- causal root-cause attribution, LLM-generated RCA, or causal probability;
- automatic remediation and cross-session project lineage.

The legacy synchronous paired-run and `omit_one_duplicate_read_v1` scope is
frozen historical research, not this MVP's current scope.
