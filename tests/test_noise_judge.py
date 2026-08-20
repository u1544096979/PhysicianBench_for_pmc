from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection.materialize import materialize
from pipeline.noise_injection.judge import NoiseJudge

class StubClient:
    def __init__(self, decision_by_value=None):
        self.decision_by_value = decision_by_value or {
            "一般情况可": {"related_to_answer": False, "contradicts": False, "reason": "ok"},
        }
    def chat_json(self, messages, node=None, **_kw):
        import json, re
        m = " ".join(x.get("content","") for x in messages)
        val = None
        for v in self.decision_by_value:
            if v in json.dumps(m, ensure_ascii=False) or v in m:
                val = self.decision_by_value[v]
                break
        return val or {"related_to_answer": False, "contradicts": True, "reason": "default reject"}

def _ctx():
    ev = [{"group_id":"g","category":"入院","feature_name":"x","value":"y","event_date":"2023-01-01"}]
    return build_context(case_id="c1", events=ev, task_type="T1_staging",
                         target_group_id="g", target_date="2023-03-01",
                         instruction="i", ground_truth={"stage":"pT2N1M0"})

def test_judge_batch_size_and_verdict():
    ctx = _ctx()
    plan = {"layer_a": [
        {"category":"病程","feature_name":"病程","value":"一般情况可","event_date":"2023-02-01","unit":""},
        {"category":"病程","feature_name":"病程","value":"今天吃了止痛药","event_date":"2023-02-02","unit":""},
    ], "episodes": []}
    rows = materialize(ctx, plan)
    # 自行构造 csv_fields 使 row_text 可用（materialize 已含）
    judge = NoiseJudge(StubClient(), batch_size=1)
    passed, rejected = judge.judge(ctx, rows, batch_size=1)
    assert len(passed) == 1 and len(rejected) == 1
    assert passed[0]["csv_fields"]["value"] == "一般情况可"
