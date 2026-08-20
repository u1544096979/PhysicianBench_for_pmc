from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection.injection import run_injection
from pipeline.noise_injection.config import NoiseConfig

GOOD_PLAN = {"layer_a": [
    {"category":"病程","feature_name":"病程","value":"一般情况可","event_date":"2023-02-01","unit":""},
], "episodes": []}

class StubClient:
    def __init__(self, plan=GOOD_PLAN, plan_counts=None, eval_verdict="valid",
                 judge_ok=True, fail_solvable_rounds=0):
        self.plan = plan; self.eval_verdict = eval_verdict; self.judge_ok = judge_ok
        self.plan_calls = 0
    def chat_json(self, messages, node=None, **_kw):
        if node == "noise_plan":
            self.plan_calls += 1
            return self.plan
        if node == "noise_judge":
            return {"related_to_answer": not self.judge_ok, "contradicts": False, "reason":"r"}
        if node == "noise_solve":
            return {"answer":"PR","reasoning_summary":"对比缩小30%判定PR"}
        if node == "noise_evaluate":
            import json
            v = self.eval_verdict
            return {"verdict": v, "consistent": v=="valid", "has_reasoning": True, "explanation":""}
        raise AssertionError(node)

def _ctx():
    ev = [{"group_id":"g","category":"入院","feature_name":"x","value":"y","event_date":"2023-01-01"}]
    return build_context(case_id="c1", events=ev, task_type="T2_response",
                         target_group_id="g", target_date="2023-03-01",
                         instruction="评估疗效", ground_truth={"response":"PR"})

def test_happy_noisy():
    res = run_injection(_ctx(), NoiseConfig(noise_rows=3, episodes=1, max_attempts=1), StubClient())
    assert res.final_status == "noisy" and res.rows

def test_degraded_clean_when_all_fail():
    client = StubClient(eval_verdict="inconsistent")
    res = run_injection(_ctx(), NoiseConfig(noise_rows=3, episodes=1, max_attempts=2), client)
    assert res.final_status == "degraded_clean"
    assert res.rows == [] and res.degrade_reason

def test_retry_reduced_params_applied():
    # 让 noise_plan 在 attempt1 抛错 → 触发降级路径
    class F:
        def chat_json(self, messages, node=None, **kw):
            if node == "noise_plan":
                raise RuntimeError("gen fail")
            raise AssertionError(node)
    res = run_injection(_ctx(), NoiseConfig(noise_rows=60, episodes=2, max_attempts=2), F())
    assert res.final_status == "degraded_clean"
