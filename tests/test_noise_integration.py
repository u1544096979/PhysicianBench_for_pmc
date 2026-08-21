"""端到端集成：仓库内真实 v2 任务目录 + 真实 raw CSV + stub client，
跑完整 run_injection 编排（planner→materialize→三道闸门），断言落盘行窗口."""
from __future__ import annotations
import sys, json
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import case_from_csv
from pipeline.noise_injection.injection import run_injection
from pipeline.noise_injection.config import NoiseConfig

NOISE_PLAN = {"layer_a": [
    {"category":"病程","feature_name":"病程","value":"一般情况可，饮食睡眠良好","event_date":"2023-06-01","unit":""},
    {"category":"检验","feature_name":"白细胞计数","value":"5.2","unit":"×10^9/L","event_date":"2023-06-02"},
    {"category":"评估","feature_name":"体温","value":"36.6","unit":"℃","event_date":"2023-06-03"},
], "episodes": []}

STUB_DATES = tuple(r["event_date"] for r in NOISE_PLAN["layer_a"])


class Stub:
    def chat_json(self, messages, node=None, **kw):
        if node=="noise_plan": return NOISE_PLAN
        if node=="noise_judge": return {"related_to_answer":False,"contradicts":False,"reason":"ok"}
        if node=="noise_solve": return {"answer":"PR","reasoning_summary":"对比可见证据缩小30%"}
        if node=="noise_evaluate": return {"verdict":"valid","consistent":True,"has_reasoning":True,"explanation":"ok"}
        raise AssertionError(node)


def _load_case(task_dir: Path):
    case_id = task_dir.name
    gt = json.loads((task_dir/"ground_truth.json").read_text(encoding="utf-8"))
    instruction = (task_dir/"instruction.md").read_text(encoding="utf-8")
    raw = PROJECT_ROOT/"data/oncology_complete_trajectory/raw/csv"/f"{case_id}.csv"
    ctx = case_from_csv(case_id, raw, task_type=gt["task_type"],
                        target_group_id=gt["target_group_id"], target_date=gt["target_date"],
                        instruction=instruction, ground_truth=gt["ground_truth"])
    return case_id, gt, instruction, raw, ctx


def _pick_real_task() -> Path | None:
    """选第一个（按名称排序）日期窗口 [first_event_date, target_date) 覆盖全部
    stub 噪声日期的 v2 任务目录；无可用任务返回 None（测试 skip）."""
    root = PROJECT_ROOT/"tasks"/"oncology-v2"
    if not root.is_dir():
        return None
    for t in sorted(root.iterdir()):
        if not t.is_dir() or not (t/"ground_truth.json").is_file():
            continue
        raw = PROJECT_ROOT/"data/oncology_complete_trajectory/raw/csv"/f"{t.name}.csv"
        if not raw.is_file():
            continue
        try:
            _, _, _, _, ctx = _load_case(t)
        except Exception:
            continue
        if all(ctx.first_event_date <= d < ctx.target_date for d in STUB_DATES):
            return t
    return None


# 用仓库内真实的一个 v2 任务目录（若存在），否则跳过
REAL_TASK = _pick_real_task()


def test_integration_real_task_noisy(tmp_path):
    if REAL_TASK is None:
        import pytest; pytest.skip("no v2 task present")
    case_id, gt, instruction, raw, ctx = _load_case(REAL_TASK)
    res = run_injection(ctx, NoiseConfig(noise_rows=3, episodes=1, max_attempts=1), Stub())
    assert res.final_status in ("noisy", "degraded_clean")
    if res.final_status == "noisy":
        assert len(res.rows) == 3
        # manifest.rows 与 CSV 行一致
        assert len(res.manifest["rows"]) == len(res.rows)
        evdates = [r["event_date"] for r in res.rows]
        assert all(gt["target_date"] > d >= ctx.first_event_date for d in evdates)  # 全部落在窗口内
