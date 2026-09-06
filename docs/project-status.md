# Project status

M0: DONE  
M1: HOLD  
M2: NOT STARTED

Latest repository commit: `ce7ecf4 Add repository-grounded agent context`.

Latest implementation checkpoint: `524dd47 Close raw-driven M1 integrity checks`.

Important: `524dd47` is a known-regressed implementation checkpoint and must
not be treated as an accepted M1 baseline. Worktree at this status update is
clean.

Only real fixture: official MSWE-agent demonstration
`marshmallow-code__marshmallow-1867.traj`, pinned in
`tests/fixtures/mswe_agent_demo/source_manifest.json`.

Flash: official experiments metadata, HF dataset, and archive revision were
verified; raw trajectory bytes are unavailable in this environment and Flash
schema is NOT VERIFIED.

## Known regressions / open integrity gaps in `524dd47`

1. Source-manifest completeness and source-binding audit was removed or weakened.
2. `raw_ref` ↔ `manifest.raw_sha256` / instance-identity binding must be restored.
3. `producer_ref` equality is checked but it is not dereferenced and verified
   against the exact producer-manifest blob.
4. Prior M1/M1.1 regression tests were reduced: wrong EvidenceRef blob hash,
   tampered normalized value, missing/conflicting provenance, and raw/fixture
   integrity protections must be restored.
5. Epistemically unknown producer metadata uses magic strings such as
   `"unknown"`; this violates frozen unknown semantics.
6. Malformed persisted evidence may crash audit instead of deterministically BLOCKing.
7. Persisted `normalized.environment` is not bound/audited against `raw.environment`.
8. Store loads normalized records through the concrete legacy adapter. This is
   minor boundary debt; fix only if a minimal change is obvious.

Items 1–7 are M1.2 closure work. Item 8 is not a reason for broad refactoring.
Next action: restore and execute all retained M1/M1.1 regressions, then close
the M1.2 gates through persisted-artifact audit before declaring M1 PASS.
