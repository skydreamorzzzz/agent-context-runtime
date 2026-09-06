import json
from pathlib import Path

from acr.adapters.legacy import normalize
from acr.audit import audit
from acr.store import (
 ingest_bytes,
 persist_import,
 persist_normalized,
 persist_producer,
 persist_provenance,
)

F=Path("tests/fixtures/mswe_agent_demo/marshmallow-code__marshmallow-1867.traj"); M=Path("tests/fixtures/mswe_agent_demo/source_manifest.json")
def setup(root):
 raw=F.read_bytes(); m=json.loads(M.read_text()); ref=ingest_bytes(raw,root,"mswe_agent_demo",m["instance_id"]); persist_import(root,"one",m,ref); p=persist_producer(root,"one",{"producer_kind":"test","code_revision":"unknown","adapter_name":"legacy","adapter_version":"mswe_agent_demo_traj_v1","schema_version":"1.0","config_identity":"none","created_at":"unknown"}); n,v=normalize(raw,ref,p); persist_normalized(root,"one",n); persist_provenance(root,"one",v); return n,v
def test_good_and_integrity_attacks(tmp_path):
 n,v=setup(tmp_path); assert audit(tmp_path,"one").status=="PASS"
 x=n.model_dump(); x["steps"].pop(); (tmp_path/"imports/one/normalized.json").write_text(json.dumps(x)); (tmp_path/"imports/one/provenance.jsonl").write_text("\n".join(i.model_dump_json() for i in v[:-3])+"\n"); assert audit(tmp_path,"one").status=="BLOCK"
 n,v=setup(tmp_path/"empty"); x=n.model_dump(); x["steps"]=[]; (tmp_path/"empty/imports/one/normalized.json").write_text(json.dumps(x)); (tmp_path/"empty/imports/one/provenance.jsonl").write_text(""); assert audit(tmp_path/"empty","one").status=="BLOCK"
 n,v=setup(tmp_path/"position"); x=n.model_dump(); x["steps"][0].update({k:x["steps"][5][k] for k in ("action","observation","response")}); (tmp_path/"position/imports/one/normalized.json").write_text(json.dumps(x)); hacked=[]
 for i in v:
  if i.output_object=="step:0": i=i.model_copy(update={"input_refs":[i.input_refs[0].model_copy(update={"locator":i.input_refs[0].locator.replace("/0/","/5/")})]})
  hacked.append(i)
 (tmp_path/"position/imports/one/provenance.jsonl").write_text("\n".join(i.model_dump_json() for i in hacked)+"\n"); assert "provenance_position_mismatch" in audit(tmp_path/"position","one").blocks
