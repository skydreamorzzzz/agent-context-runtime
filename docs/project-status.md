# Project status

- M0: DONE.
- M1: HOLD — M1.2 final integrity closure remains to be independently reviewed
  against all retained regression gates.
- M2: NOT STARTED.
- Latest local/remote-intended commit: `524dd47 Close raw-driven M1 integrity checks`.
- Worktree at compaction: clean (`git status --short` produced no entries).
- Only real fixture: official MSWE-agent demonstration
  `marshmallow-code__marshmallow-1867.traj`, pinned in
  `tests/fixtures/mswe_agent_demo/source_manifest.json`.
- Flash: official metadata/revision verified; raw archive bytes unavailable in
  this environment; Flash schema NOT VERIFIED.

Next action: continue only M1.2 from the persisted-artifact tests and audit
path; first restore/verify every listed M1/M1.1 regression before declaring
M1 PASS.
