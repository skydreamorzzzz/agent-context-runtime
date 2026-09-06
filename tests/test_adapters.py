import hashlib
import json
from pathlib import Path

from acr.adapters.legacy import normalize
from acr.store import ingest_bytes, load_blob

FIXTURE=Path("tests/fixtures/mswe_agent_demo/marshmallow-code__marshmallow-1867.traj")
MANIFEST=Path("tests/fixtures/mswe_agent_demo/source_manifest.json")
def test_real_fixture_ingests_idempotently_and_normalizes(tmp_path):
    raw=FIXTURE.read_bytes(); manifest=json.loads(MANIFEST.read_text())
    assert hashlib.sha256(raw).hexdigest()==manifest["raw_sha256"]
    first=ingest_bytes(raw,tmp_path,"mswe_agent_demo",manifest["instance_id"]); second=ingest_bytes(raw,tmp_path,"mswe_agent_demo",manifest["instance_id"])
    assert first.blob_hash==second.blob_hash and load_blob(tmp_path,first.blob_hash)==raw
    one=normalize(raw,first); two=normalize(raw,second)
    assert one==two and len(one.steps)==14 and len(one.provenance)>=3
    assert one.steps[0].source_position==0
    for item in one.provenance[:3]: assert item.input_refs[0].locator.startswith("/trajectory/")
