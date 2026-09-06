"""Fixed parser for the observed MSWE-agent demonstration .traj schema."""
from __future__ import annotations

import json

from acr.contracts import Envelope, EvidenceRef, Provenance

ADAPTER_VERSION="mswe_agent_demo_traj_v1"
class NormalizedBatchRecord(Envelope):
    adapter_version:str; environment:str; steps:list[dict]
def normalize(raw:bytes,raw_ref:EvidenceRef,producer_ref:EvidenceRef)->tuple[NormalizedBatchRecord,list[Provenance]]:
    doc=json.loads(raw)
    if set(doc)!={"environment","trajectory","history","info"} or not isinstance(doc["trajectory"],list): raise ValueError("unsupported MSWE-agent demonstration schema")
    steps=[]; provenance=[]
    for i,step in enumerate(doc["trajectory"]):
        if set(step)!={"action","observation","response","state","thought"} or not all(isinstance(step[k],str) for k in step): raise ValueError("unsupported MSWE-agent trajectory step schema")
        steps.append({"source_position":i,"action":step["action"],"observation":step["observation"],"response":step["response"]})
        for field in ("action","observation","response"):
            ref=raw_ref.model_copy(update={"locator":f"/trajectory/{i}/{field}"})
            provenance.append(Provenance(kind="provenance",id=f"step:{i}/{field}",producer_ref=producer_ref,output_object=f"step:{i}",field=field,input_refs=[ref],transform_name="mswe_agent_demo_extract_v1",transform_version=ADAPTER_VERSION))
    return NormalizedBatchRecord(kind="normalized_batch",id="normalized",producer_ref=producer_ref,adapter_version=ADAPTER_VERSION,environment=doc["environment"],steps=steps),provenance
