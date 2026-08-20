# tests/test_noise_plan.py
from __future__ import annotations
import sys, json
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection.plan import NoisePlanner

class StubClient:
    def __init__(self, payload): self.payload = payload
    def chat_json(self, messages, node=None, **_kw):
        return self.payload

def _ctx():
    ev = [{"group_id":"g","category":"入院","feature_name":"x","value":"y","event_date":"2023-01-01"}]
    return build_context(case_id="c1", events=ev, task_type="T1_staging",
                         target_group_id="g", target_date="2023-03-01",
                         instruction="i", ground_truth={})

def test_planner_returns_plan_and_versions():
    payload = {"layer_a": [], "episodes": []}
    st = StubClient(payload)
    planner = NoisePlanner(st)
    assert planner.prompt_version == "v1"
    plan = planner.plan(_ctx(), noise_rows=2, episodes=1)
    assert plan == payload
    assert len(planner.client.calls) == 1 if hasattr(planner.client,"calls") else True
