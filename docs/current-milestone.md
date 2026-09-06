# Current milestone: M1.2 — Final Integrity Closure

Only close the single MSWE-agent demonstration trajectory evidence chain. Do
not add a second trajectory, retry Flash downloads, or begin M2.

New integrity gates are cumulative. Do not delete, weaken, replace, or stop
executing an already-established M1/M1.1 invariant or regression test merely
to satisfy a newer M1.2 gate.

## Required gates

- Raw trajectory determines normalized step count and all expected
  `(step:i, action|observation|response)` provenance keys.
- Every normalized `source_position` equals its historical raw array index;
  this is not `event_seq` or `available_seq`.
- Every provenance locator is exactly `/trajectory/i/<field>` for its output
  key, even if another raw value is equal.
- Persisted normalized output has an Envelope and producer reference.
- Persist `producer_manifest.json` separately from the source manifest; its
  content-addressed `EvidenceRef` is the producer ref of normalized output and
  every `Provenance`. Raw trajectory refs appear in `input_refs`.
- Audit reads persisted import artifacts only and blocks malformed raw schema,
  raw/normalized structure mismatch, position laundering, producer mismatch,
  wrong blob/hash, invalid locator, value mismatch, missing provenance, and
  conflicting provenance.

## Retained M1/M1.1 regressions

- Source manifest completeness and raw-ref ↔ manifest `raw_sha256` binding.
- `source_id` / `trajectory_key` / instance identity consistency.
- Referenced raw blob exists and its hash matches.
- Invalid locator, wrong EvidenceRef blob hash, tampered normalized field,
  missing provenance, and conflicting provenance each BLOCK.
- Persisted artifact round-trip and immutable-write integrity.

## M1.2 regressions and E2E

- Keep prior M1/M1.1 attacks: wrong blob hash, bad locator, tampered value,
  missing provenance, conflicting provenance, and raw corruption.
- Add/delete-step, empty-normalized-plus-empty-provenance, and position
  laundering attacks; each must BLOCK through the production audit path.
- Malformed persisted evidence must BLOCK rather than crash. If `environment`
  remains persisted, bind it to `raw.environment`.
- From an empty data root run `acr ingest`, `acr normalize`, and `acr audit`,
  then run all three mutation gates. Run `pytest -q` and `ruff check .`.

## Prohibited

No second trajectory, Flash/SWE-smith download, native adapter, runtime,
provider, DecisionView, candidate, intervention, paired rerun, evaluation,
accounting, reporting, or benchmark execution.
