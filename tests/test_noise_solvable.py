from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection.materialize import materialize
from pipeline.noise_injection import solvable

class StubClient:
    def __init__(self, solve=None, evaluate=None):
        self.solve = solve or {"answer": "PR", "reasoning_summary": "对比基线与随访影像，长径缩小>30%，判定PR"}
        self.evaluate = evaluate or {"verdict": "valid", "consistent": True, "has_reasoning": True, "explanation": "ok"}
        self.calls = []
    def chat_json(self, messages, node=None, **_kw):
        self.calls.append(node)
        if node == "noise_solve": return self.solve
        if node == "noise_evaluate": return self.evaluate
        raise AssertionError(node)

def _ctx():
    ev = [{"group_id":"g","category":"入院","feature_name":"x","value":"y","event_date":"2023-01-01"}]
    return build_context(case_id="c1", events=ev, task_type="T2_response",
                         target_group_id="g", target_date="2023-03-01",
                         instruction="评估疗效", ground_truth={"response":"PR"})

def test_solvable_valid_passes():
    ctx = _ctx()
    rows = materialize(ctx, {"layer_a": [
        {"category":"病程","feature_name":"病程","value":"一般情况可","event_date":"2023-02-01","unit":""},
    ], "episodes": []})
    st = StubClient()
    ok, detail = solvable.check(ctx, rows, st)
    assert ok is True and "noise_solve" in st.calls and "noise_evaluate" in st.calls

def test_solvable_verdict_not_valid_fails():
    ctx = _ctx()
    rows = materialize(ctx, {"layer_a": [], "episodes": []})
    st = StubClient(evaluate={"verdict": "inconsistent", "consistent": False,
                              "has_reasoning": True, "explanation": "no"})
    ok, detail = solvable.check(ctx, rows, st)
    assert ok is False
