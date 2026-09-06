import json
from pathlib import Path

from acr.adapters.legacy import normalize
from acr.audit import audit
from acr.store import ingest_bytes, persist_import, persist_normalized, persist_provenance

F=Path("tests/fixtures/mswe_agent_demo/marshmallow-code__marshmallow-1867.traj"); M=Path("tests/fixtures/mswe_agent_demo/source_manifest.json")
def setup(tmp):
 raw=F.read_bytes(); m=json.loads(M.read_text()); ref=ingest_bytes(raw,tmp,"mswe_agent_demo",m["instance_id"]); persist_import(tmp,"one",m,ref); n,p=normalize(raw,ref); persist_normalized(tmp,"one",n); persist_provenance(tmp,"one",p); return n,p
def test_persisted_chain_and_mutations(tmp_path):
 n,p=setup(tmp_path); assert audit(tmp_path,"one").status=="PASS"
 n["steps"][0]["action"]="malicious replacement"; (tmp_path/"imports/one/normalized.json").write_text(json.dumps(n))
 assert "normalized_value_mismatch" in audit(tmp_path,"one").blocks
 _,p=setup(tmp_path/"hash"); p[0]=p[0].model_copy(update={"input_refs":[p[0].input_refs[0].model_copy(update={"blob_hash":"0"*64})]}); (tmp_path/"hash/imports/one/provenance.jsonl").write_text("\n".join(x.model_dump_json() for x in p)+"\n")
 assert "referenced_blob_missing" in audit(tmp_path/"hash","one").blocks
def test_missing_and_conflicting_provenance_block(tmp_path):
 _,p=setup(tmp_path); (tmp_path/"imports/one/provenance.jsonl").write_text("\n".join(x.model_dump_json() for x in p[1:])+"\n"); assert "required_provenance_missing" in audit(tmp_path,"one").blocks
 _,p=setup(tmp_path/"conflict"); (tmp_path/"conflict/imports/one/provenance.jsonl").write_text("\n".join(x.model_dump_json() for x in p+[p[0]])+"\n"); assert "conflicting_provenance" in audit(tmp_path/"conflict","one").blocks
