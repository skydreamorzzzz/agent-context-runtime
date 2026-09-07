# Project status

M0: DONE
M1: DONE
M2: DONE
M2 Observation Protocol: DONE
M2 Trusted Capture: DONE
Real provider smoke: PASS

Latest implementation checkpoint: `6a8141d` — evaluator producer/private-spec
provenance closure and isolated evaluator execution workspace.

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

M2 trusted-capture engineering integrity closure: COMPLETE. The persisted
audit closes physical-attempt inventory, exact request occurrence, runtime
producer, and runtime config identity in addition to the prior exception,
usage, state, and file-read gates. This is not whole M2 completion; real smoke
and evaluator gates remain unstarted.

Real provider smoke: PASS. The frozen DeepSeek `deepseek-v4-flash` public
add-task smoke ran from clean revision `86aef1a`, produced two physical attempts
and one exact file read, sealed successfully, and passed persisted audit. The
response/usage/run artifacts remain local and are not committed. Provider usage
was observed; no price or task-quality claim is made.

M1 DONE denotes the historical persisted-evidence closure only. M2 native
trusted capture is DONE: the preserved real run has a sealed-artifact-bound,
independent private evaluator result with `resolved=false`. The model's text
answer was not treated as a workspace patch or a positive evaluation.

The original local evaluator artifact predates the final producer-identity
closure and is retained without alteration. A later local-only evaluator
observation against the same preserved sealed real artifact records the actual
clean evaluator code revision, exact producer-manifest blob, and private-spec
SHA256; runtime and evaluation audits PASS. Raw run/evaluation data and private
specs remain ignored and uncommitted.

Next gate: M3 noop / A-A remains a separate authorization decision. Do not
extend synthetic integrity scope absent a new explicit P0 finding.
