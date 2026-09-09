# Contract conventions

## Active F0 Agent Forensics contracts

`src/acr/forensics_contracts.py` defines exactly five provisional top-level
record types:

- primary evidence: `AgentEvent`, `WorkspaceCheckpoint`, and
  `VerificationReceipt`;
- derived view: `IncidentReport`;
- action receipt: `ForkReceipt`.

Every record serializes `contract_status=provisional_until_f0_5_pass`; the module
also declares **PROVISIONAL UNTIL F0.5 PASS**. F0 proves only construction,
strict validation, serialization round trips, and the ability to represent the
synthetic fixture. Fields may be revised or rejected during F0.5.

The contracts reuse legacy `ContractModel`, `Envelope`, `EvidenceRef`, and
`Fact/status/reason` semantics without importing `Candidate`, `DecisionView`,
`InterventionPlan`, or `RequestSnapshot` into the Forensics model.

`captured_workspace_manifest_hash` is fixed in F0 to the explicitly captured
repository scope. `manifest_scope` cannot claim a full repository, workspace,
environment, process, machine, or model state. Capture gaps make completeness
false or unknown; privacy exclusions are not bypassed.

The provisional canonical manifest is deterministic JSON over only its format,
Git base identity, and a path-sorted captured overlay. Each overlay entry names
the repository-relative path, tracked or selected-untracked classification,
present or deleted state, and content hash when present. Checkpoint occurrence
metadata—ID, session, ordering, timestamp, trigger, event ID, evidence locator,
and incident metadata—is excluded. Identical captured state can therefore share
one manifest hash across distinct checkpoint occurrences, while a Git-base or
overlay change changes the state identity. `manifest_ref.blob_hash` must equal
`captured_workspace_manifest_hash` because both identify the canonical manifest
bytes. This format is still provisional and has no restore-fidelity claim.

`VerificationReceipt` names its `pre_checkpoint_id` and the tested captured
manifest hash. An optional post-checkpoint must be a different checkpoint and is
never the tested state. `IncidentReport` is explicitly `derived_view`, requires
provenance, admits only false/unknown entries in `capture_gaps`, and rejects
causal fields through strict extra-field validation.
`ForkReceipt` is schema-only in F0 and limits its claim scope to captured
repository state; the fixture records it as `not_executed`.

Cross-record receipt integrity is a future evidence-set/journal requirement:
the pre-checkpoint must resolve in the same session, its manifest hash must equal
the receipt's tested hash, and ordering/execution correlation must be valid. A
standalone F0 `VerificationReceipt` does not prove those relationships.

No F0 contract establishes Claude Hook fields, event ordering, checkpoint
capture, verifier execution, restoration, fork fidelity, or analyzer behavior.

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
