# Multi-SWE-bench Flash duplicate-read coverage audit

## Source and audit

- Dataset: `ByteDance-Seed/Multi-SWE-bench_trajs`
- Revision: `9180bb0c633e4580fc8f74629ac6a47b8582543f`
- Artifact: `flash/20250725_MopenHands_Qwen3-Coder-480B-A35B.zip`
- Archive SHA256: `7f0b0c5b65bd019ee3971a1dca2fd087294396ebf347e5321fcc85ccbea024bf`
- Adapter: `multi_swe_bench_flash_openhands_v1`
- Detector: `exact_duplicate_complete_read_v1`
- Reproducibility audit: **PASS**

The pinned archive contains 258 JSON trajectories; 258 were readable.
This is the archive actually scanned, not an assumption that every advertised Flash task is present.

Re-run from a local copy of the pinned archive:

```bash
acr scan-duplicate-reads \
  --archive data/mswe_duplicate_read_audit/20250725_MopenHands_Qwen3-Coder-480B-A35B.zip \
  --source-manifest configs/multi_swe_bench_flash_coverage.json \
  --output docs/coverage/multi-swe-bench-flash-duplicate-read-v1.json \
  --report docs/coverage/multi-swe-bench-flash-duplicate-read-v1.md
```

## Coverage

| Measure | Result |
| --- | ---: |
| File-read occurrences | 3606 |
| Trajectories with repeated same-path reads | 253 / 258 (98.1%) |
| Repeated same-path read occurrences | 2056 |
| Trajectories with exact duplicate read output | 58 / 258 (22.5%) |
| Exact duplicate read outputs | 78 |
| Exact duplicates reported as complete output | 21 |
| Exact duplicate output bytes | 84843 |
| Strict legal candidates | 0 |
| Strict removable bytes | 0 |
| Exact duplicates with an intervening same-path edit | 21 |

Candidate token estimate/share are **unknown**: exact tokenizer and actual request membership are not evidenced.

## Evidence limits

The event list proves distinct read occurrences, source positions, paths, and exact recorded tool-output
strings. It does not prove authoritative runtime sequence, exact original file bytes/encoding, the two
results' simultaneous membership in an actual outbound request, or a pre-send current-file state check.
Those missing facts are not defaulted to success. Shell `run` actions between reads are treated as
unresolved possible changes rather than parsed heuristically.

`exact_duplicate_precondition` examples in the machine artifact are not strict candidates. The strict
positive list is empty because no candidate passes the frozen evidence predicate.

## Decision: NO_GO

The archive shows exact repeated read outputs, but it does not evidence exact source-file bytes/encoding, actual request co-membership, or a current state check; zero strict legal candidates can therefore be established fail-closed.

This result measures prevalence and theoretical duplicate output bytes only. It does **not** establish
quality preservation, API cost savings, behavioral rebound, extra reads/tests/retries, or intervention
effectiveness. The next justified evidence step is native/request-level capture on a bounded workload,
not a formal deletion paired run based solely on this archive.
