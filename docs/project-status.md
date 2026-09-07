# Project status

M0: DONE
M1: DONE
M2: IN PROGRESS

Latest implementation checkpoint: repository HEAD — M2 trusted-capture
engineering integrity closure in progress.

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

## M2.0 current status

M2 is authorized for the observation-protocol and engineering-only trusted
capture slice. The runtime captures persisted request/attempt/response/tool/
file/state/seal evidence and audits it through an explicitly synthetic
engineering transport fixture. Its closure now includes exception attempts,
one-to-one attempt sets, raw-response usage binding, phase-specific repository
state, sealed-state closure, and exact file-read occurrence binding.

M2 trusted-capture engineering integrity closure: COMPLETE. This is not whole
M2 completion; real smoke and evaluator gates remain unstarted.

Real provider smoke: BLOCKED / NOT RUN. `configs/pilot.json` remains a template
and does not freeze a provider, model, task manifest, image digest, or budget.
No credential, provider, or model has been selected or inferred. Therefore no
real task execution, provider-observed usage, evaluator result, task-quality,
or cost claim exists.

M1 DONE denotes the historical persisted-evidence closure only. M2 native
trusted capture is in progress; the engineering fixture does not satisfy the
frozen plan's real-task/evaluator M2 completion condition.
