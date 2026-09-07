# Project status

M0: DONE
M1: DONE
M2: DONE
M3 Noop/A-A paired-run feasibility: PASS
M3 overall: IN PROGRESS

Latest implementation checkpoint: `a833b62` — persisted M3 noop A/A pair
harness and audit.

Current context/document baseline: repository HEAD.

The accepted M1 source fixture remains the official MSWE-agent demonstration
`marshmallow-code__marshmallow-1867.traj`; Flash raw bytes remain unavailable
and its schema is not verified.

M2 has a preserved local-only DeepSeek real smoke and an independently audited
private evaluator result. The raw runtime/evaluation evidence and private spec
are ignored and uncommitted.

One real DeepSeek `deepseek-v4-flash` noop A/A pair completed at clean revision
`a833b62`: two fresh independent workspaces, two sealed/evaluated runs, and a
persisted pair audit all passed. Provider-cache isolation remains unsupported.
This is a single-pair M3 feasibility result, not the frozen plan's full
multi-task M3 completion and not evidence of intervention effectiveness.

Next gate: authorize one deterministic candidate and the smallest real
baseline/treatment intervention pair; do not expand A/A synthetic scope.
