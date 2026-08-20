from __future__ import annotations
import sys, json
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.manifest import build_manifest, write_manifest, read_manifest, MANIFEST_SCHEMA_VERSION

def test_manifest_roundtrip(tmp_path, ):
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION, "case_id": "c1", "task_type": "T2_response",
        "generated_at": "2026-08-20T00:00:00Z",
        "config_snapshot": {"noise_rows": 60, "episodes": 2, "prompt_versions": {"plan":"v1","judge":"v1"}, "model": "m"},
        "attempts": [{"attempt":1,"rows_requested":60,"rows_passed":58,
                      "gates":{"rule_rejected":2,"judge_rejected":3,"solvable":"valid"},"failure_reason":None}],
        "final_status": "noisy",
        "rows": [{"csv_row":57,"group_id":"g","layer":"A","episode_id":None,
                  "category":"检验","feature_name":"白细胞计数","value":"5.2",
                  "event_date":"2023-07-02","judge":"pass"}],
    }
    p = tmp_path / "noise_manifest.json"
    write_manifest(p, manifest)
    loaded = read_manifest(p)
    assert loaded["final_status"] == "noisy"
    assert loaded["rows"][0]["csv_row"] == 57

def test_build_manifest_degraded_has_empty_rows():
    m = build_manifest(case_id="c1", task_type="T2_response", generated_at="t",
                       config_snapshot={}, attempts=[],
                       final_status="degraded_clean", rows=[])
    assert m["final_status"] == "degraded_clean" and m["rows"] == []
