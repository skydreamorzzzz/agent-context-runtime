# M2 Observation Protocol: Trusted Capture Boundaries

This protocol freezes what the runtime may call observed. It applies to the
M2 capture slice; it does not claim a real-provider smoke or evaluator result.
All persistent top-level records use the `Envelope` convention and all raw
bytes enter the content-addressed store before normalized records are made.

| Fact | Observation boundary and raw evidence | Observed / derived limits | Occurrence identity and contract binding | Fail-closed and adversarial check |
|---|---|---|---|---|
| Actual outbound request | The exact byte object passed to `CapturedProvider`'s physical transport call; store it before calling transport. | Only `sent_body_ref` is observed outbound content. Draft and prepared bodies are separate evidence and may differ. Server-internal prompt state is not observed. | Each physical `attempt_id` has `before_body_ref`, `prepared_body_ref`, and `sent_body_ref` in `RequestSnapshot`; a request `Event` repeats those refs. | A prepared/sent divergence test verifies `sent_body_ref` names transport bytes, not a reserialized prepared object. Missing/mismatched refs BLOCK. |
| Physical provider attempt | One invocation of the physical transport. | Transport status and provider request ID are observed only when returned by transport. A transport exception has failure evidence, no fabricated provider response/ID, and unknown usage. A logical call is not an attempt count. | `attempt:<run-id>:<n>` is independent of event sequence and content hash. One snapshot, request event, and exactly one terminal response/failure event must exist per attempt. | Retry, deleted/orphan/duplicate attempt records, and transport-exception mutations BLOCK. |
| Provider response | Raw bytes returned by transport, stored unchanged. | Parsed fields are observed only through a JSON Pointer into these raw bytes. No replay response is a new real observation. | Response `Event.payload_ref` contains `raw_response_ref`, tied to its run and attempt. | Missing/blob-corrupt/wrong-run response evidence BLOCK. |
| Provider-reported usage | `/usage` in a parseable raw response only. | Such usage is `Fact(status=observed)` with the response locator ref. Absent/non-object usage is `Fact(status=unknown, reason=provider_did_not_report_usage)`. Local token estimates are not implemented. | `raw_usage_ref` and the sole `Fact.refs` item must be the same response blob, run identity, and `/usage` locator; the Fact value must equal the resolved raw value. | Missing usage, value/ref/locator mutation, and invented usage BLOCK. |
| Tool call | Runtime tool invocation and its terminal result. | A tool result is usable only after its `tool_finish`; an unfinished start creates no visible result fact. | `tool:<run-id>:<n>` is an occurrence identity. `tool_start` and `tool_finish` are authoritative serial `Event.event_seq` records. | Removing finish or exposing result before finish BLOCKs. |
| Exact file read | `read_file` resolves a workspace-relative regular path, opens and reads actual UTF-8 bytes once, then stores those bytes. | A `FileBinding` is observed only for these bytes/path/mode/read occurrence. Tool text alone does not prove a file read. | Binding carries path, SHA256, encoding, unique `read_event_id`, and exact finish `observed_seq`; body locator is `/tools/<call-id>/body`. | Changed same-path bytes, same bytes twice, traversal, symlink escape, binding/sequence/call-ID/locator laundering, and body/hash replacement BLOCK. |
| Repository state | Before start: deterministic manifest of regular workspace files. At seal: deterministic final tree; file bindings cover only observed reads. | Initial/final tree hashes are derived from their own raw manifests. Image digest is observed only from supplied frozen config evidence; otherwise `Fact(unknown, reason=runtime_image_digest_not_observed)`. No full restore claim. | `RepositoryState(state_phase=initial)` has `initial_tree_hash`; `state_phase=final` has `final_tree_hash`. Both bind a tree ref; `Run` separately binds initial/final state records and final sealed tree. Tree identity excludes physical workspace directory name. | Workspace symlinks/protected-root overlap reject start. State-ref, tree, producer, run, hash, or final-seal mismatch BLOCKs. |
| Final artifact | After `run_stop`, runtime hashes the final workspace manifest and binds it in `Run.sealed_artifact_ref/hash`. | It proves final captured tree, not task success or patch validity. | One sealed `Run`; normal evidence writes after seal are rejected. | Post-seal append and hash mismatch tests BLOCK. |
| Evaluation result | A separate evaluator process/domain receives only a sealed run plus private spec. | No evaluation is observed in this slice; no `EvaluationResult` is synthesized. | Existing `EvaluationResult` contract remains evaluator-owned; runtime task has no private-spec field. | Protected evaluator root overlapping workspace rejects start; unsealed runs must be rejected by future evaluator boundary. |

## Cross-cutting rules

- `Event.event_seq` is the authoritative synchronous runtime order. Historical
  `source_position` is not used by this runtime.
- Content SHA256 identifies bytes only. Call IDs, attempt IDs, event IDs, tool
  IDs, and evidence locators preserve occurrence identity.
- `CapturedProvider.send()` is the only physical send path and refuses an
  unbound capture run. Raw payloads are stored before their `Event`, `RequestSnapshot`, or
  `FileBinding` is created. Runtime audit only reads persisted artifacts and
  returns `BLOCK` for malformed data rather than repairing it.
- The engineering fixture transport exists only to test wiring. It is labelled
  `engineering_fixture_only` and cannot establish real-provider, task-quality,
  usage-price, or evaluator claims.
