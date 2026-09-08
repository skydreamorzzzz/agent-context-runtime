# Audit checklist

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
- Failed attempts and manager overhead remain in the ledger.
- No unresolved `block` finding exists.
- The report is reproducible from sealed artifacts without API calls.

## Summary

An absent field, unavailable capability, or incomplete cost is reported as `unknown`, `unsupported`, or `not_applicable`. It is not converted to a zero, success, or inferred value.
