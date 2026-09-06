# Contract conventions

Persistent records use the envelope `kind`, `schema_version`, `id`, `producer_ref`, and `provenance_ref`. Observations with uncertain availability use `Fact(value, status, reason, refs)`; observed and derived facts require evidence references.

Unknown is a first-class outcome. Content hashes identify bytes, while IDs identify logical or execution identity.
