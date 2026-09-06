import json
from pathlib import Path

from acr.adapters.legacy import normalize
from acr.audit import audit
from acr.store import ingest_bytes

FIXTURE=Path("tests/fixtures/mswe_agent_demo/marshmallow-code__marshmallow-1867.traj")
MANIFEST=Path("tests/fixtures/mswe_agent_demo/source_manifest.json")
def prepared(tmp_path):
    raw=FIXTURE.read_bytes(); manifest=json.loads(MANIFEST.read_text()); ref=ingest_bytes(raw,tmp_path,"mswe_agent_demo",manifest["instance_id"]); return raw,manifest,ref,normalize(raw,ref)
def test_good_real_fixture_audits_pass(tmp_path):
    _,manifest,_,normalized=prepared(tmp_path); assert audit(tmp_path,manifest,normalized).status=="PASS"
def test_bad_hash_and_locator_and_provenance_block(tmp_path):
    raw,manifest,ref,normalized=prepared(tmp_path)
    blob=tmp_path/"blobs"/ref.blob_hash; blob.write_bytes(raw+b"x")
    assert "hash_mismatch" in audit(tmp_path,manifest,normalized).blocks
    blob.write_bytes(raw)
    bad=normalized.__class__(normalized.environment,normalized.steps,(normalized.provenance[0].__class__("step:0","action",(ref.model_copy(update={"locator":"/bad"}),),"x","v"),))
    assert audit(tmp_path,manifest,bad).status=="BLOCK"
    empty=normalized.__class__(normalized.environment,normalized.steps,())
    assert "required_provenance_missing" in audit(tmp_path,manifest,empty).blocks
