import json
from pathlib import Path

from acr.adapters.legacy import NormalizedBatchRecord, normalize
from acr.store import ingest_bytes, persist_producer

F=Path("tests/fixtures/mswe_agent_demo/marshmallow-code__marshmallow-1867.traj"); M=Path("tests/fixtures/mswe_agent_demo/source_manifest.json")
def test_fixed_schema_and_formal_normalized_envelope(tmp_path):
 raw=F.read_bytes(); m=json.loads(M.read_text()); ref=ingest_bytes(raw,tmp_path,"mswe_agent_demo",m["instance_id"]); producer=persist_producer(tmp_path,"one",{"producer_kind":"test","code_revision":"unknown","adapter_name":"legacy","adapter_version":"mswe_agent_demo_traj_v1","schema_version":"1.0","config_identity":"none","created_at":"unknown"}); normalized,provenance=normalize(raw,ref,producer)
 assert isinstance(normalized,NormalizedBatchRecord) and normalized.producer_ref==producer and len(normalized.steps)==14 and all(x.producer_ref==producer for x in provenance)
