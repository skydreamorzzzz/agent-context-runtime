# Contract conventions

Persistent records use the envelope `kind`, `schema_version`, `id`, `producer_ref`, and `provenance_ref`. Observations with uncertain availability use `Fact(value, status, reason, refs)`; observed and derived facts require evidence references.

Unknown is a first-class outcome. Content hashes identify bytes, while IDs identify logical or execution identity.

For M2, `RequestSnapshot` keeps separate optional `prepared_body_ref` and
`sent_body_ref`: prepared bytes do not establish actual outbound bytes. A
`RepositoryState.image_digest` is a `Fact[str]`, so a runtime without observed
image evidence records explicit `unknown + reason` rather than a sentinel.
`RepositoryState.state_phase` keeps `initial_tree_hash` and `final_tree_hash`
semantically disjoint; each state binds its own raw tree reference.
