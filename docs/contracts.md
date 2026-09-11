# Contract conventions

## Active Agent Forensics contracts

`src/acr/forensics_contracts.py` defines five top-level record types:

- primary evidence: `AgentEvent`, `WorkspaceCheckpoint`, and
  `VerificationReceipt`;
- derived view: `IncidentReport`;
- action receipt: `ForkReceipt`.

Historical F0 records serialize
`contract_status=provisional_pending_separate_freeze`. F1 production
`AgentEvent`, `WorkspaceCheckpoint`, and `VerificationReceipt` records serialize
`contract_status=v0.1_frozen`; their runtime-required nested capture and
canonicalization semantics are frozen with them. `IncidentReport` and
`ForkReceipt` remain provisional.

The contracts reuse legacy `ContractModel`, `Envelope`, `EvidenceRef`, and
`Fact/status/reason` semantics without importing `Candidate`, `DecisionView`,
`InterventionPlan`, or `RequestSnapshot` into the Forensics model.

`captured_workspace_manifest_hash` is fixed in F0 to the explicitly captured
repository scope. `manifest_scope` cannot claim a full repository, workspace,
environment, process, machine, or model state. Capture gaps make completeness
false or unknown; privacy exclusions are not bypassed.

The v0.1-compatible canonical manifest is deterministic JSON over only its format,
Git base identity, and a path-sorted captured overlay. Each overlay entry names
the repository-relative path, tracked or selected-untracked classification,
present or deleted state, content hash when present, and executable boolean for
every captured present regular file. Deleted paths use `None` because executable
state is not applicable. Checkpoint occurrence
metadata—ID, session, ordering, timestamp, trigger, event ID, evidence locator,
and incident metadata—is excluded. Identical captured state can therefore share
one manifest hash across distinct checkpoint occurrences, while a Git-base or
overlay change changes the state identity. `WorkspaceCheckpoint` recomputes the
canonical hash from `git_base` and `captured_paths`; both
`captured_workspace_manifest_hash` and `manifest_ref.blob_hash` must equal that
expected value. Agreement between the two stored fields alone is insufficient.
The historical format label remains `acr.captured-state-manifest/0.2-provisional`
to preserve byte-for-byte F0.5 compatibility; F1 freezes those exact bytes for
the production slice. A golden regression uses committed conditional-closure
evidence to prevent drift. There is no broader or complete-workspace
restore-fidelity claim.

`VerificationReceipt` names its `pre_checkpoint_id` and the tested captured
manifest hash. An optional post-checkpoint must be a different checkpoint and is
never the tested state. For frozen receipts, `passed=true` requires an observed
exit code of zero, while `passed=false` requires an observed non-zero exit code.
A Bash failure hook without stable exit-code evidence remains event evidence and
cannot become a trusted receipt. `IncidentReport` is explicitly `derived_view`,
requires provenance, admits only false/unknown entries in `capture_gaps`, and
rejects causal fields through strict extra-field validation.
`ForkReceipt` is schema-only in F0 and limits its claim scope to captured
repository state; the fixture records it as `not_executed`.

The F1 production session audit resolves each receipt's pre-checkpoint in the
same session, requires identical tested/checkpoint manifest hashes, and verifies
the exact verifier's hashed Claude session plus tool-use occurrence correlation.
Receipt-eligible terminal evidence must resolve to exactly one receipt;
unclassified failure or interruption events may resolve to none. If correlation
or terminal evidence is unsupported or missing, no trusted receipt is emitted. A
standalone historical F0 `VerificationReceipt` still does not prove those
relationships.

F1 establishes only the production runtime slice above. It does not establish
restoration, fork fidelity, Failure Window derivation, or analyzer behavior.

## Legacy Context Optimization conventions

This section records implemented Context Optimization contract conventions. It
remains historical authority for those records, but it does not redefine the
provisional Agent Forensics schemas.

Persistent records use the envelope `kind`, `schema_version`, `id`,
`producer_ref`, and `provenance_ref`. Observations with uncertain availability
use `Fact(value, status, reason, refs)`; observed and derived facts require
evidence references.

Unknown is a first-class outcome. Content hashes identify bytes, while IDs
identify logical or execution identity.

For M2, `RequestSnapshot` keeps separate optional `prepared_body_ref` and
`sent_body_ref`: prepared bytes do not establish actual outbound bytes. A
`RepositoryState.image_digest` is a `Fact[str]`, so a runtime without observed
image evidence records explicit `unknown + reason` rather than a sentinel.
`RepositoryState.state_phase` keeps `initial_tree_hash` and `final_tree_hash`
semantically disjoint; each state binds its own raw tree reference.
