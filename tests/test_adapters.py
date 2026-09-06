import hashlib
import json
from pathlib import Path

from acr.adapters.legacy import normalize
from acr.contracts import Provenance
from acr.store import ingest_bytes, load_blob

F=Path("tests/fixtures/mswe_agent_demo/marshmallow-code__marshmallow-1867.traj"); M=Path("tests/fixtures/mswe_agent_demo/source_manifest.json")
def test_real_fixture_normalizes_with_official_provenance(tmp_path):
 raw=F.read_bytes(); m=json.loads(M.read_text()); ref=ingest_bytes(raw,tmp_path,"mswe_agent_demo",m["instance_id"]); n,p=normalize(raw,ref)
 assert hashlib.sha256(raw).hexdigest()==m["raw_sha256"] and load_blob(tmp_path,ref.blob_hash)==raw and len(n["steps"])*3==len(p)
 assert [Provenance.model_validate_json(x.model_dump_json()) for x in p]==p
