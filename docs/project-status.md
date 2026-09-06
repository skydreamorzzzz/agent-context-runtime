# Project status

M0: DONE
M1: DONE
M2: NOT STARTED

Latest implementation checkpoint: repository HEAD — M1.2 final integrity
closure.

Current context/document baseline: repository HEAD (including the Git
credential-hygiene handoff protocol).

The former `524dd47` checkpoint contained known regressions and is not the
accepted M1 baseline. Its source-binding, producer-reference, malformed-input,
environment-binding, and retained-regression gaps were closed at repository
HEAD.

Only real fixture: official MSWE-agent demonstration
`marshmallow-code__marshmallow-1867.traj`, pinned in
`tests/fixtures/mswe_agent_demo/source_manifest.json`.

Flash: official experiments metadata, HF dataset, and archive revision were
verified; raw trajectory bytes are unavailable in this environment and Flash
schema is NOT VERIFIED.

## Accepted M1 evidence-chain closure

- Source manifest completeness, raw-ref/hash/instance binding, and exact raw
  blob integrity are audited from persisted artifacts.
- Producer manifests are separate immutable blobs; normalized output and every
  provenance record must reference the exact persisted producer ref.
- The raw trajectory fixes expected step count, field coverage, source position,
  exact JSON Pointer, and normalized value for all `action`, `observation`, and
  `response` fields.
- Retained and new attacks BLOCK: bad blob/hash, bad locator, tampered value,
  missing/conflicting provenance, raw corruption, deleted/empty steps, position
  laundering, malformed persisted evidence, and environment mismatch.
- Provenance input refs must name the exact persisted raw blob for this import;
  a different valid blob with matching source labels and field value BLOCKs.
- The source manifest is checked against the frozen MSWE-agent repository,
  revision, artifact path, instance identity, and raw SHA256 rather than merely
  requiring non-empty strings.

Minor boundary debt remains: `store.py` loads the fixed normalized record via
the concrete legacy adapter. It is outside M1's accepted scope and is not a
reason to broaden this milestone.

Next action: remain at M1 completion until M2 is explicitly authorized.
M1 DONE denotes this re-frozen historical persisted-evidence closure; trusted
native capture is not included in this completion and is deferred to later
explicitly authorized runtime work.
