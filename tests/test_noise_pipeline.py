from __future__ import annotations
import sys, json, csv
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from pipeline.oncology_generation import nodes as N
from pipeline.oncology_generation.graph import run_case

HEADER = "group_id,event_date,category,feature_name,value,extra_value,_source_row\n"
def make_case_csv(tmp_path, case_id):
    data_root = tmp_path / "csv"; data_root.mkdir(exist_ok=True)
    rows = HEADER
    rows += 'g1,2018-03-01,病理,病理诊断,浸润性导管癌,,1\n'
    rows += 'g1,2018-03-01,病理,免疫组化,HER2 3+,,2\n'
    rows += 'g1,2018-03-01,病史,既往史,否认高血压史,,3\n'
    rows += 'g2,2018-11-26,诊断,诊断名称,乳腺癌,,4\n'
    rows += 'g2,2018-11-26,诊断,临床分期,pT2N1M0,,5\n'
    (data_root/f"{case_id}.csv").write_text(rows, encoding="utf-8")
    return data_root

NOISE_PLAN = {"layer_a": [
    {"category":"病程","feature_name":"病程","value":"一般情况可，饮食睡眠良好",
     "event_date":"2018-05-01","unit":""},
    {"category":"检验","feature_name":"白细胞计数","value":"5.2","unit":"×10^9/L",
     "event_date":"2018-05-02"},
], "episodes": []}

class FakeClient:
    def __init__(self):
        self.calls=[]
    def chat_json(self, prompt, node=None, **_kw):
        self.calls.append(node)
        if node=="label": return {"applicable_types":["T1_staging"],"recommended_type":"T1_staging","reason":"r"}
        if node=="generate": return {"target_group_id":"g2","target_date":"2018-11-26",
                                     "instruction":"判定分期","ground_truth":{"stage":"pT2N1M0"},
                                     "answer_event_rows":[]}
        if node=="validate": return {"passed":True,"issues":[],"severity":"","leaked":False,"answerable":True,"unique":True}
        if node=="solve": return {"answer":"pT2N1M0 II期","reasoning_summary":"病理浸润性导管癌","confidence":"high"}
        if node=="evaluate": return {"verdict":"valid","consistent":True,"has_reasoning":True,"explanation":"ok"}
        if node=="checkpoint": return {"checkpoints":[
            {"id":"c1","layer":"data_retrieval","description":"d","eval_method":"category_query","params":{}},
            {"id":"c2","layer":"clinical_reasoning","description":"d","eval_method":"llm_judge","params":{}},
            {"id":"c3","layer":"outcome_check","description":"d","eval_method":"field_match","params":{}},
            {"id":"c4","layer":"documentation","description":"d","eval_method":"llm_judge","params":{}}]}
        if node=="noise_plan": return NOISE_PLAN
        if node=="noise_judge": return {"related_to_answer":False,"contradicts":False,"reason":"ok"}
        if node=="noise_solve": return {"answer":"pT2N1M0","reasoning_summary":"病理示浸润性导管癌"}
        if node=="noise_evaluate": return {"verdict":"valid","consistent":True,"has_reasoning":True,"explanation":"ok"}
        raise AssertionError(node)

def test_pipeline_appends_noise_and_writes_manifest(tmp_path):
    case_id="case_noise"
    N.get_default_client = lambda trace_dir=None: FakeClient()
    final = run_case(case_id, data_root=make_case_csv(tmp_path,case_id),
                     output_root=tmp_path/"tasks", generated_root=tmp_path/"generated")
    assert final["status"]=="persisted"
    assert final.get("noise_rows") and final.get("noise_manifest")
    assert final["noise_manifest"]["final_status"]=="noisy"
    task_dir=Path(final["task_dir"])
    assert (task_dir/"noise_manifest.json").exists()
    cleaned=(task_dir/"cleaned_trajectory.csv").read_text(encoding="utf-8")
    assert "一般情况可" in cleaned and "白细胞计数" in cleaned
    # 降级/评审队列不影响主差异：这里应为 noisy
    assert final["noise_manifest"]["rows"]


def test_pipeline_degraded_clean(tmp_path):
    """降级路径回归：noise_evaluate 判 inconsistent → 重试阶梯耗尽 →
    degraded_clean，任务仍以干净版 persisted，manifest 落盘 + review_queue 记录."""
    class DegradeClient(FakeClient):
        def chat_json(self, prompt, node=None, **kw):
            if node == "noise_evaluate":
                return {"verdict": "inconsistent", "consistent": False,
                        "has_reasoning": True, "explanation": "加噪后答案不稳"}
            return super().chat_json(prompt, node=node, **kw)
    case_id = "case_deg"
    N.get_default_client = lambda trace_dir=None: DegradeClient()
    final = run_case(case_id, data_root=make_case_csv(tmp_path, case_id),
                     output_root=tmp_path / "tasks", generated_root=tmp_path / "generated")
    assert final["status"] == "persisted"
    m = final["noise_manifest"]
    assert m["final_status"] == "degraded_clean" and m["rows"] == []
    task_dir = Path(final["task_dir"])
    assert (task_dir / "noise_manifest.json").exists()
    assert json.loads((task_dir / "noise_manifest.json").read_text(encoding="utf-8"))["final_status"] == "degraded_clean"
    queue = (tmp_path / "generated/review_queue.jsonl").read_text(encoding="utf-8")
    assert "noise_gate_failed" in queue and case_id in queue
