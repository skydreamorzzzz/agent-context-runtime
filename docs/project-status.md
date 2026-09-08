# Project status

M0: DONE
M1: DONE
M2 provider/runtime capture: PASS
M2 independent evaluator: PASS
M2 real coding-agent loop / reconstructible seal / usage ledger: CODE COMPLETE,
real-provider validation pending
M3 Noop/A-A paired-run feasibility: PASS
M3 semantic/execution binding: CODE COMPLETE, real-pair revalidation pending
M3 overall: IN PROGRESS

Latest implementation checkpoint: `9a9d83d` — frozen public task instruction
bound to the actual serialized provider request.

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

Next gate: finish and verify the real coding-loop integrity closure. Do not
authorize a candidate or intervention until its persisted runtime, evaluator,
usage, and pair binding audits pass.

Latest local-only real-loop attempt at revision `669a78b` completed one HTTP
provider attempt and retained the real response; its persisted runtime audit
passed, but the model did not request a file read or edit the workspace. The run
was truthfully sealed as `task_failed` and is not accepted as a completed real
coding-agent-loop result. No automatic retry was made.

The four confirmed code-level closure items are now covered: text-only answers
cannot edit the workspace, duplicate read messages retain exact occurrence
bindings, pair audit compares only the frozen hard attempt maximum, and CLI
acceptance uses the configured 1..hard-max range. No deletion/intervention was
implemented.

The task manifest's `public_instruction` now supplies the real loop's initial
user message; an offline transport regression verifies the exact sent request
body. Code-level P0 closure is complete; real-provider validation is pending.
