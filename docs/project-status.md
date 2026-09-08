# Project status

M0: DONE
M1: DONE
M2 provider/runtime capture: PASS
M2 independent evaluator: PASS
M2 real coding-agent loop / reconstructible seal / usage ledger: PASS
M3 Noop/A-A paired-run feasibility: PASS
M3 semantic/execution binding: CODE COMPLETE, real-pair revalidation pending
M3 overall: IN PROGRESS

Latest implementation checkpoint: `2844605` — strict text-command protocol
captured in the provider request with task-manifest instruction binding intact.

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

Next gate: an exact duplicate-read candidate and a minimal intervention before
any baseline/treatment paired rerun. No deletion/intervention is implemented yet.

Latest local-only real-loop attempt at clean revision `2844605` followed the
strict protocol through `READ`, explicit `WRITE`, `TEST`, and `FINAL`. It used
four physical attempts, changed the fresh workspace, sealed as `completed`, and
passed the persisted runtime audit. No evaluator was invoked by this smoke path.

The four confirmed code-level closure items are now covered: text-only answers
cannot edit the workspace, duplicate read messages retain exact occurrence
bindings, pair audit compares only the frozen hard attempt maximum, and CLI
acceptance uses the configured 1..hard-max range. No deletion/intervention was
implemented.

The task manifest's `public_instruction` now supplies the real loop's initial
user message; an offline transport regression verifies the exact sent request
body. Real-provider coding-loop validation is PASS.
