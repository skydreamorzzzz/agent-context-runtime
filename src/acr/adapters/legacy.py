"""Fixed parser for the observed MSWE-agent demonstration ``.traj`` schema."""

from __future__ import annotations

import json
from typing import Any

from acr.contracts import ContractModel, Envelope, EvidenceRef, Provenance

ADAPTER_VERSION = "mswe_agent_demo_traj_v1"
_STEP_FIELDS = ("action", "observation", "response", "state", "thought")
_NORMALIZED_FIELDS = ("action", "observation", "response")


class LegacyStep(ContractModel):
    """The small, adapter-local projection of one historical trajectory step."""

    source_position: int
    action: str
    observation: str
    response: str


class NormalizedBatchRecord(Envelope):
    """Persisted envelope for this fixed-format historical import only."""

    adapter_version: str
    environment: str
    steps: list[LegacyStep]


def parse_document(raw: bytes) -> dict[str, Any]:
    """Validate exactly the schema observed in the frozen real fixture."""

    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid MSWE-agent demonstration JSON") from exc
    if not isinstance(document, dict) or set(document) != {
        "environment",
        "trajectory",
        "history",
        "info",
    }:
        raise ValueError("unsupported MSWE-agent demonstration schema")
    if not isinstance(document["environment"], str) or not isinstance(document["trajectory"], list):
        raise TypeError("unsupported MSWE-agent demonstration schema")
    if not isinstance(document["history"], list) or not isinstance(document["info"], dict):
        raise TypeError("unsupported MSWE-agent demonstration schema")
    for step in document["trajectory"]:
        if not isinstance(step, dict) or set(step) != set(_STEP_FIELDS):
            raise ValueError("unsupported MSWE-agent trajectory step schema")
        if not all(isinstance(step[field], str) for field in _STEP_FIELDS):
            raise ValueError("unsupported MSWE-agent trajectory step schema")
    return document


def normalize(
    raw: bytes,
    raw_ref: EvidenceRef,
    producer_ref: EvidenceRef,
) -> tuple[NormalizedBatchRecord, list[Provenance]]:
    """Normalize only fields directly present in the fixed historical artifact."""

    document = parse_document(raw)
    steps: list[LegacyStep] = []
    provenance: list[Provenance] = []
    for index, step in enumerate(document["trajectory"]):
        steps.append(
            LegacyStep(
                source_position=index,
                action=step["action"],
                observation=step["observation"],
                response=step["response"],
            )
        )
        for field in _NORMALIZED_FIELDS:
            input_ref = raw_ref.model_copy(update={"locator": f"/trajectory/{index}/{field}"})
            provenance.append(
                Provenance(
                    kind="provenance",
                    id=f"step:{index}/{field}",
                    producer_ref=producer_ref,
                    output_object=f"step:{index}",
                    field=field,
                    input_refs=[input_ref],
                    transform_name="mswe_agent_demo_extract_v1",
                    transform_version=ADAPTER_VERSION,
                )
            )
    return (
        NormalizedBatchRecord(
            kind="normalized_batch",
            id=f"normalized:{raw_ref.trajectory_key}",
            producer_ref=producer_ref,
            adapter_version=ADAPTER_VERSION,
            environment=document["environment"],
            steps=steps,
        ),
        provenance,
    )
