from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection import prompts as NP

def _events():
    return [
        {"group_id":"g0","category":"入院","subject":"患者","feature_name":"入院年龄",
         "value":"66","event_date":"2023-03-01","_record_source":"论文病例报告"},
        {"group_id":"g1","category":"检验","subject":"血液","feature_name":"白细胞计数",
         "value":"5.2","event_date":"2023-06-14"},
        {"group_id":"g2","category":"影像","subject":"胸部CT","feature_name":"影像结论",
         "value":"右上叶肿块","event_date":"2023-06-14"},
        {"group_id":"g3","category":"病理","subject":"","feature_name":"CEA","value":"3.1",
         "event_date":"2023-07-02"},
        {"group_id":"g4","category":"病史","subject":"患者","feature_name":"既往史",
         "value":"否认高血压、糖尿病史","event_date":"2023-03-01"},
        {"group_id":"gt","category":"评估","subject":"患者","feature_name":"疗效评估",
         "value":"PR","event_date":"2023-08-14"},
    ]

def test_build_context_fields():
    ev = _events()
    ctx = build_context(
        case_id="c1", events=ev, task_type="T2_response",
        target_group_id="gt", target_date="2023-08-14",
        instruction="评估疗效", ground_truth={"response":"PR"},
    )
    assert ctx.first_event_date == "2023-03-01"
    assert ctx.encnt_no == ""
    # 关键证据日 = 目标组 + 可见中含肿瘤标志物的检验组 + 影像组
    assert {ctx.target_date} <= set(ctx.key_evidence_dates)
    assert "2023-06-14" in ctx.key_evidence_dates  # 影像组日期
    assert "2023-06-14" in ctx.key_evidence_dates  # 含CEA的检验组日期
    assert "2023-07-02" in ctx.key_evidence_dates
    # 否认模式提取
    assert "高血压" in ctx.denial_terms and "糖尿病" in ctx.denial_terms
    # 惯例采样：检验→血液
    assert ctx.convention_by_category["检验"]["subject"] == "血液"

def test_convention_fallback():
    ev = [{"group_id":"g","category":"入院","feature_name":"x","value":"y","event_date":"2023-01-01"}]
    ctx = build_context(case_id="c2", events=ev, task_type="T1_staging",
                        target_group_id="g", target_date="2023-03-01",
                        instruction="i", ground_truth={})
    # 无既有检验行 → 回退 catalog 默认
    assert ctx.convention_by_category["检验"]["subject"] == "血液"

def test_prompt_versions_and_builders():
    assert set(NP.PROMPT_VERSIONS) == {"plan","judge"}
    ev = _events()
    ctx = build_context(case_id="c1", events=ev, task_type="T2_response",
                        target_group_id="gt", target_date="2023-08-14",
                        instruction="评估疗效", ground_truth={"response":"PR"})
    msgs = NP.build_plan_prompt(ctx, noise_rows=3, episodes=1)
    text = " ".join(m["content"] for m in msgs)
    assert "c1" in text and "2023-08-14" in text
    assert "否认" in text  # 病例事实注入
    judge_msgs = NP.build_judge_prompt(ctx, [{"row": {"category": "病程", "value": "一般情况可"}}])
    jtext = " ".join(m["content"] for m in judge_msgs)
    assert "judge" in jtext.lower() or "裁判" in jtext
