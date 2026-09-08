"""Small persisted usage ledger; money stays unknown without price evidence."""

from __future__ import annotations

from acr.contracts import CostEntry, EvidenceRef, Fact


def usage_entries(
    *, run_id: str, producer_ref: EvidenceRef, attempts: list[tuple[str, Fact[dict], EvidenceRef | None]]
) -> tuple[list[CostEntry], dict[str, object]]:
    """Normalize provider-reported token fields without inventing missing usage."""

    entries: list[CostEntry] = []
    totals = {"input_tokens": 0.0, "output_tokens": 0.0, "total_tokens": 0.0}
    observed = True
    for attempt_id, usage, usage_ref in attempts:
        raw = usage.value if usage.status == "observed" and isinstance(usage.value, dict) else None
        if raw is None:
            observed = False
            raw = {}
        values = {
            "input_tokens": raw.get("input_tokens", raw.get("prompt_tokens")),
            "output_tokens": raw.get("output_tokens", raw.get("completion_tokens")),
            "total_tokens": raw.get("total_tokens"),
        }
        if values["total_tokens"] is None and all(isinstance(values[key], (int, float)) for key in ("input_tokens", "output_tokens")):
            values["total_tokens"] = values["input_tokens"] + values["output_tokens"]
        for category, value in values.items():
            fact = Fact[float](value=float(value), status="derived", refs=[usage_ref]) if isinstance(value, (int, float)) and usage_ref else Fact[float](status="unknown", reason="provider_did_not_report_token_field")
            if fact.status == "observed" or fact.status == "derived":
                totals[category] += fact.value or 0.0
            entries.append(CostEntry(kind="cost_entry", id=f"cost:{run_id}:{attempt_id}:{category}", producer_ref=producer_ref, run_id=run_id, attempt_id=attempt_id, caller="agent", phase="run", category=category, quantity=fact, unit="tokens", amount=Fact[float](status="unknown", reason="price_not_verified"), evidence_level="provider_reported_usage" if raw is not None else "usage_unknown", raw_usage_ref=usage_ref, dedup_key=f"{attempt_id}:{category}"))
            if fact.status == "unknown":
                observed = False
    aggregate: dict[str, object] = {"physical_attempt_count": len(attempts), "usage_complete": observed}
    aggregate.update(totals if observed else {key: None for key in totals})
    return entries, aggregate
