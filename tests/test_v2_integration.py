"""v2 流水线集成测试（假LLM，验证路由/打回/落盘）."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.oncology_generation import nodes as N  # noqa: E402
from pipeline.oncology_generation.graph import run_case  # noqa: E402

# 构造一个最小 case CSV：2个事件组
CASE_CSV_HEADER = "group_id,event_date,category,feature_name,value,extra_value,_source_row\n"


def make_case_csv(tmp_path: Path, case_id: str) -> Path:
    data_root = tmp_path / "csv"
    data_root.mkdir(exist_ok=True)
    rows = CASE_CSV_HEADER
    rows += 'g1,2018-03-01,病理,病理诊断,浸润性导管癌,,1\n'
    rows += 'g1,2018-03-01,病理,免疫组化,HER2 3+,,2\n'
    rows += 'g2,2018-11-26,诊断,诊断名称,乳腺癌,,3\n'
    rows += 'g2,2018-11-26,诊断,临床分期,pT2N1M0,,4\n'
    (data_root / f"{case_id}.csv").write_text(rows, encoding="utf-8")
    return data_root


GOOD_LABEL = {
    "applicable_types": ["T1_staging"],
    "recommended_type": "T1_staging",
    "reason": "存在明确分期记录且前有病理证据",
}
GOOD_GENERATE = {
    "target_group_id": "g2",
    "target_date": "2018-11-26",
    "instruction": "请判定该患者的肿瘤分期并输出报告。",
    "ground_truth": {"stage": "pT2N1M0"},
    "rationale": "首次明确分期记录，证据链完整",
}
GOOD_VALIDATE = {
    "passed": True,
    "issues": [],
    "severity": "",
    "detail": "无泄漏、可推理、答案唯一",
}
GOOD_SOLVE = {
    "answer": "pT2N1M0 II期",
    "reasoning": "病理示浸润性导管癌，结合影像评估分期为pT2N1M0",
}
GOOD_EVALUATE = {
    "verdict": "valid",
    "reason": "答案与标签一致且推理完整",
}
GOOD_CHECKPOINTS = {
    "checkpoints": [
        {"id": "cp1", "layer": "data_retrieval", "check": "查询了病理事件",
         "eval_method": "category_query", "target": "病理"},
        {"id": "cp2", "layer": "clinical_reasoning", "check": "正确识别HER2状态",
         "eval_method": "llm_judge", "rubric": "输出中体现HER2 3+"},
        {"id": "cp3", "layer": "outcome_check", "check": "T分期正确",
         "eval_method": "field_match", "field": "stage", "expect": "pT2N1M0"},
        {"id": "cp4", "layer": "documentation", "check": "报告包含结构化字段",
         "eval_method": "llm_judge", "rubric": "含分期字段"},
    ]
}
# 噪声注入（evaluate valid 分支总走 inject_noise）：一条安全的病程噪声，日期在病例窗口内
GOOD_NOISE_PLAN = {
    "layer_a": [
        {"category": "病程", "feature_name": "病程", "value": "一般情况可",
         "event_date": "2018-05-01", "unit": ""},
    ],
    "episodes": [],
}
GOOD_NOISE_JUDGE = {"related_to_answer": False, "contradicts": False, "reason": "ok"}
GOOD_NOISE_SOLVE = {"answer": "pT2N1M0", "reasoning_summary": "病理示浸润性导管癌"}
GOOD_NOISE_EVALUATE = {
    "verdict": "valid", "consistent": True, "has_reasoning": True, "explanation": "ok",
}


class FakeClient:
    def __init__(self, script: dict, fail_nodes: list[str] | None = None,
                 fail_times: int = 99):
        self.script = script
        self.fail_nodes = fail_nodes or []
        self.fail_times = fail_times
        self.calls: list[str] = []

    def chat_json(self, prompt, node=None, **_kw):
        self.calls.append(node)
        if node in self.fail_nodes and self.fail_times > 0:
            self.fail_times -= 1
            if node == "validate":
                return {"passed": False, "issues": ["证据不足"], "severity": "major",
                        "detail": "截断前无影像"}
            if node == "evaluate":
                return {"verdict": "inconsistent", "reason": "答案不符"}
        return self.script[node]


def _run(tmp_path, case_id, fake):
    N.get_default_client = lambda trace_dir=None: fake
    return run_case(
        case_id,
        data_root=make_case_csv(tmp_path, case_id),
        output_root=tmp_path / "tasks",
        generated_root=tmp_path / "generated",
    )


def test_happy_path_persists_task_package(tmp_path):
    case_id = "case_ok"
    fake = FakeClient({
        "label": GOOD_LABEL, "generate": GOOD_GENERATE, "validate": GOOD_VALIDATE,
        "solve": GOOD_SOLVE, "evaluate": GOOD_EVALUATE, "checkpoint": GOOD_CHECKPOINTS,
        "noise_plan": GOOD_NOISE_PLAN, "noise_judge": GOOD_NOISE_JUDGE,
        "noise_solve": GOOD_NOISE_SOLVE, "noise_evaluate": GOOD_NOISE_EVALUATE,
    })
    final = _run(tmp_path, case_id, fake)
    assert final["status"] == "persisted"
    task_dir = Path(final["task_dir"])
    assert (task_dir / "instruction.md").exists()
    gt = json.loads((task_dir / "ground_truth.json").read_text(encoding="utf-8"))
    assert gt["ground_truth"]["stage"] == "pT2N1M0"
    assert gt["task_type"] == "T1_staging"
    cps = json.loads((task_dir / "checkpoints.json").read_text(encoding="utf-8"))
    layers = {c["layer"] for c in cps["checkpoints"]}
    assert layers == {"data_retrieval", "clinical_reasoning", "outcome_check", "documentation"}
    # 清洗后的csv只保留g1（截断逻辑正确）
    cleaned = (task_dir / "cleaned_trajectory.csv").read_text(encoding="utf-8")
    assert "pT2N1M0" not in cleaned and "乳腺癌" not in cleaned
    assert "浸润性导管癌" in cleaned
    # 标注持久化
    label_file = tmp_path / "generated/labels" / f"{case_id}.json"
    assert json.loads(label_file.read_text(encoding="utf-8"))["recommended_type"] == "T1_staging"


def test_validate_fail_then_pass_via_retry(tmp_path):
    case_id = "case_retry"
    fake = FakeClient({
        "label": GOOD_LABEL, "generate": GOOD_GENERATE, "validate": GOOD_VALIDATE,
        "solve": GOOD_SOLVE, "evaluate": GOOD_EVALUATE, "checkpoint": GOOD_CHECKPOINTS,
        "noise_plan": GOOD_NOISE_PLAN, "noise_judge": GOOD_NOISE_JUDGE,
        "noise_solve": GOOD_NOISE_SOLVE, "noise_evaluate": GOOD_NOISE_EVALUATE,
    }, fail_nodes=["validate"], fail_times=1)
    final = _run(tmp_path, case_id, fake)
    assert final["status"] == "persisted"
    # validate被调用了两次（1失败+1通过）
    assert fake.calls.count("validate") == 2
    assert fake.calls.count("generate") == 2


def test_all_retries_exhausted_goes_review_queue(tmp_path):
    case_id = "case_dead"
    fake = FakeClient({
        "label": GOOD_LABEL, "generate": GOOD_GENERATE, "validate": GOOD_VALIDATE,
        "solve": GOOD_SOLVE, "evaluate": GOOD_EVALUATE, "checkpoint": GOOD_CHECKPOINTS,
        "noise_plan": GOOD_NOISE_PLAN, "noise_judge": GOOD_NOISE_JUDGE,
        "noise_solve": GOOD_NOISE_SOLVE, "noise_evaluate": GOOD_NOISE_EVALUATE,
    }, fail_nodes=["validate"], fail_times=99)
    final = _run(tmp_path, case_id, fake)
    assert final["status"] == "review_queue"
    assert final["review_reason"] == "validation_failed"
    queue = (tmp_path / "generated/review_queue.jsonl").read_text(encoding="utf-8")
    assert case_id in queue
    assert fake.calls.count("generate") == 3  # MAX_ATTEMPTS


def test_evaluate_fail_routes_back(tmp_path):
    case_id = "case_eval"
    fake = FakeClient({
        "label": GOOD_LABEL, "generate": GOOD_GENERATE, "validate": GOOD_VALIDATE,
        "solve": GOOD_SOLVE, "evaluate": GOOD_EVALUATE, "checkpoint": GOOD_CHECKPOINTS,
        "noise_plan": GOOD_NOISE_PLAN, "noise_judge": GOOD_NOISE_JUDGE,
        "noise_solve": GOOD_NOISE_SOLVE, "noise_evaluate": GOOD_NOISE_EVALUATE,
    }, fail_nodes=["evaluate"], fail_times=1)
    final = _run(tmp_path, case_id, fake)
    assert final["status"] == "persisted"
    assert fake.calls.count("evaluate") == 2
    assert fake.calls.count("generate") == 2


def test_label_none_goes_review_queue(tmp_path):
    case_id = "case_none"
    fake = FakeClient({
        "label": {"applicable_types": [], "recommended_type": "none",
                  "reason": "数据太薄"},
        "generate": GOOD_GENERATE, "validate": GOOD_VALIDATE,
        "solve": GOOD_SOLVE, "evaluate": GOOD_EVALUATE, "checkpoint": GOOD_CHECKPOINTS,
        "noise_plan": GOOD_NOISE_PLAN, "noise_judge": GOOD_NOISE_JUDGE,
        "noise_solve": GOOD_NOISE_SOLVE, "noise_evaluate": GOOD_NOISE_EVALUATE,
    })
    final = _run(tmp_path, case_id, fake)
    assert final["status"] == "review_queue"
    assert final["review_reason"] == "label_unsuitable"
    assert "generate" not in fake.calls  # 不应进入生成


def test_literal_leak_detected_at_persist(tmp_path):
    case_id = "case_leak"
    leak_gen = dict(GOOD_GENERATE)
    leak_gen["instruction"] = "请判断分期是否为pT2N1M0并输出报告。"
    fake = FakeClient({
        "label": GOOD_LABEL, "generate": leak_gen, "validate": GOOD_VALIDATE,
        "solve": GOOD_SOLVE, "evaluate": GOOD_EVALUATE, "checkpoint": GOOD_CHECKPOINTS,
        "noise_plan": GOOD_NOISE_PLAN, "noise_judge": GOOD_NOISE_JUDGE,
        "noise_solve": GOOD_NOISE_SOLVE, "noise_evaluate": GOOD_NOISE_EVALUATE,
    }, fail_nodes=["validate"], fail_times=0)  # validate全通过
    # 落盘时字面泄漏检测应把状态置为review_queue（materialize失败按review处理）
    final = _run(tmp_path, case_id, fake)
    assert final["status"] == "review_queue"
    assert "leak" in final["review_reason"]
