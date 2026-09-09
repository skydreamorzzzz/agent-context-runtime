# Audit checklist

> **LEGACY STATUS:** This checklist governs the implemented Context Optimization
> pair/intervention evidence path. It is preserved and frozen; it is not the
> active Agent Forensics validation checklist.

Before a pair is included in a report, verify:

- Raw request, response, tool, and usage evidence is addressable by content hash.
- Normalized objects have schema version, producer reference, and provenance reference.
- The DecisionView contains only same-run, completed, authorized prefix evidence;
  future, evaluator/private, tainted, cross-run, and unknown-label inputs block.
- Every ContextBlock resolves to its exact public/config, provider-response, or
  completed tool occurrence; content equality cannot substitute for identity.
- A candidate has two distinct complete `read_file` calls and a persisted current
  file comparison whose exact `state_check` occurrence and re-read evidence
  prove status `same`; its provenance labels match the canonical origin.
- The receipt proves the actual sent body, not merely an intended prepared body.
- Baseline and treatment have independently verified initial state, frozen config, and recorded order.
- The run is sealed before the evaluator accesses private inputs.
- Submitted code runs with an empty/minimal environment, a read-only workspace,
  sandbox-private temporary storage, disabled network access, bounded output,
  and a hard timeout that remains active after output pipes close.
- Both pair arms are sealed before either evaluator producer's recorded start;
  the boundary comes from each persisted event stream's unique final completed
  `run_stop.end`, and pair audit blocks timestamp laundering.
- Failed attempts and manager overhead remain in the ledger.
- No unresolved `block` finding exists.
- The report is reproducible from sealed artifacts without API calls.

## Summary

An absent field, unavailable capability, or incomplete cost is reported as `unknown`, `unsupported`, or `not_applicable`. It is not converted to a zero, success, or inferred value.
