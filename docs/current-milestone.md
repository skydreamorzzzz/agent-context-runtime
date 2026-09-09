# Current milestone: offline duplicate-read candidate coverage audit

M0–M2 are DONE. M3 noop A/A feasibility has passed while M3 overall remains
IN PROGRESS. Infrastructure P0 and Pre-M4 trust closure remain frozen. M4 is
NOT STARTED.

This gate measures only the prevalence of the frozen exact duplicate complete
`read_file` research object in historical Multi-SWE-bench data. It does not
perform request rewriting, an intervention, or a paired treatment run.

## Frozen scan

- Input: the official `ByteDance-Seed/Multi-SWE-bench_trajs` Flash OpenHands
  archive at dataset revision `9180bb0c633e4580fc8f74629ac6a47b8582543f`.
- Adapter: `multi_swe_bench_flash_openhands_v1`; it accepts only the observed
  event-list shape and treats array position as `source_position`, never as an
  authoritative runtime sequence.
- Detector: `exact_duplicate_complete_read_v1`; paths, content identity,
  occurrence identity, completeness, UTF-8 file identity, request membership,
  intervening changes, and current state all fail closed when unsupported.
- Outputs: a deterministic JSON coverage artifact and a concise report under
  `docs/coverage/`, with traceable exact/rejected/unknown examples.

## Result

`OFFLINE_DUPLICATE_READ_COVERAGE_AUDIT_PASS`

The archive contains 258 JSON trajectories and all were readable. Exact
recorded read-output duplicates occur, but the archive does not prove exact
source-file bytes/encoding, actual outbound-request co-membership, or a
pre-send current-file state check. It therefore establishes zero strict legal
candidates under the frozen predicate.

Decision: `NO_GO` for implementing or running `omit_one_duplicate_read_v1`
from this historical archive alone. The prevalence result is not evidence of
quality preservation, API cost savings, or behavioral rebound.

Next gate: decide whether to collect a bounded native/request-level candidate
coverage sample with the already trusted runtime. Intervention and M4 remain
unstarted unless that evidence supports a separate explicit authorization.
