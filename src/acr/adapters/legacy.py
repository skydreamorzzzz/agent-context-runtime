"""Fixed parser for the observed MSWE-agent demonstration .traj schema."""
from __future__ import annotations

import json
from dataclasses import dataclass

from acr.contracts import EvidenceRef
from acr.provenance import FieldProvenance

ADAPTER_VERSION = "mswe_agent_demo_traj_v1"

@dataclass(frozen=True)
class LegacyStep:
    source_position: int
    action: str
    observation: str
    response: str

@dataclass(frozen=True)
class NormalizedLegacyTrajectory:
    environment: str
    steps: tuple[LegacyStep, ...]
    provenance: tuple[FieldProvenance, ...]

def normalize(raw: bytes, raw_ref: EvidenceRef) -> NormalizedLegacyTrajectory:
    document = json.loads(raw)
    if set(document) != {"environment", "trajectory", "history", "info"} or not isinstance(document["trajectory"], list):
        raise ValueError("unsupported MSWE-agent demonstration schema")
    steps=[]; provenance=[]
    for index, step in enumerate(document["trajectory"]):
        if set(step) != {"action", "observation", "response", "state", "thought"} or not all(isinstance(step[k], str) for k in ("action", "observation", "response")):
            raise ValueError("unsupported MSWE-agent trajectory step schema")
        steps.append(LegacyStep(index, step["action"], step["observation"], step["response"]))
        for field in ("action", "observation", "response"):
            ref = raw_ref.model_copy(update={"locator": f"/trajectory/{index}/{field}"})
            provenance.append(FieldProvenance(f"step:{index}", field, (ref,), "mswe_agent_demo_extract_v1", ADAPTER_VERSION))
    return NormalizedLegacyTrajectory(document["environment"], tuple(steps), tuple(provenance))
