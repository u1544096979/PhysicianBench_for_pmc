from __future__ import annotations
import sys, uuid
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection.materialize import materialize, CSV_FIELDS

def _ctx():
    ev = [
        {"group_id":"g","category":"入院","subject":"患者","feature_name":"入院年龄","value":"66","event_date":"2023-03-01","_record_source":"论文病例报告"},
        {"group_id":"g1","category":"检验","subject":"血液","feature_name":"白细胞计数","value":"5.2","unit":"×10^9/L","event_date":"2023-06-14","method":"","source":"LLM提取"},
    ]
    return build_context(case_id="c1", events=ev, task_type="T2_response",
                         target_group_id="g", target_date="2023-08-14",
                         instruction="i", ground_truth={})

PLAN = {
    "layer_a": [
        {"category":"检验","feature_name":"血红蛋白","value":"125","unit":"g/L","event_date":"2023-07-01"},
        {"category":"病程","feature_name":"病程","value":"一般情况可，饮食睡眠良好","event_date":"2023-07-02","unit":""},
    ],
    "episodes": [
        {"episode_id":"ep1","days":[
            {"category":"病程","feature_name":"病程","value":"今日体温38.2°C","date_abs":"2023-07-05"},
            {"category":"评估","feature_name":"体温","value":"38.2","unit":"℃","date_abs":"2023-07-05"},
        ]},
    ],
}

def test_materialize_17_fields():
    rows = materialize(_ctx(), PLAN)
    assert len(rows) == 4
    for r in rows:
        cf = r["csv_fields"]
        assert set(CSV_FIELDS) <= set(cf)
        assert cf["case_id"] == "c1"
        assert len(cf["group_id"]) == 36  # uuid
        assert cf["event_date"] < "2023-08-14"
        assert cf["category"] in ("评估","检验","用药","病程")

def test_group_id_unique_and_no_real_group():
    rows = materialize(_ctx(), PLAN)
    gids = [r["csv_fields"]["group_id"] for r in rows]
    assert len(set(gids)) == len(gids)

def test_convention_sampled():
    rows = materialize(_ctx(), PLAN)
    lab = [r for r in rows if r["csv_fields"]["category"]=="检验"][0]
    assert lab["csv_fields"]["subject"] == "血液"  # 采样自身检验行

def test_episode_id_preserved_in_meta():
    rows = materialize(_ctx(), PLAN)
    epis = [r for r in rows if r.get("episode_id") == "ep1"]
    assert len(epis) == 2

def test_numeric_row_has_unit_and_parseable_value():
    rows = materialize(_ctx(), PLAN)
    lab = [r for r in rows if r["csv_fields"]["category"]=="检验"][0]
    assert lab["csv_fields"]["unit"]
    float(lab["csv_fields"]["value"])  # must not raise
