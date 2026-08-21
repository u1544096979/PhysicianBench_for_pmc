from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection.materialize import _row
from pipeline.noise_injection.safety import run_safety_gate, row_text

def _ctx():
    ev = [
        {"group_id":"g0","category":"入院","feature_name":"入院年龄","value":"66","event_date":"2023-03-01"},
        {"group_id":"g1","category":"影像","feature_name":"影像结论","value":"肿块","event_date":"2023-06-14"},
        {"group_id":"g2","category":"病理","feature_name":"CEA","value":"3.1","event_date":"2023-07-02"},
        {"group_id":"gt","category":"评估","feature_name":"疗效评估","value":"PR","event_date":"2023-08-14"},
        {"group_id":"g4","category":"病史","feature_name":"既往史","value":"否认高血压史","event_date":"2023-03-01"},
    ]
    return build_context(case_id="c1", events=ev, task_type="T2_response",
                         target_group_id="gt", target_date="2023-08-14",
                         instruction="评估疗效", ground_truth={"response":"PR"})

def test_date_window_enforced():
    ctx = _ctx()
    rows = [
        _row(ctx, category="病程", feature_name="病程", value="ok", unit="",
             event_date="2023-08-14", layer="A"),      # 等于截断日 → 拒
        _row(ctx, category="病程", feature_name="病程", value="ok2", unit="",
             event_date="2023-07-02", layer="A"),      # 关键证据日 → 拒（保守）
        _row(ctx, category="病程", feature_name="病程", value="ok3", unit="",
             event_date="2023-07-01", layer="A"),      # 安全
    ]
    passed, rej = run_safety_gate(ctx, rows)
    assert len(passed) == 1 and rej

def test_forbidden_category_scan():
    ctx = _ctx()
    rows = [_row(ctx, category="病理", feature_name="病理诊断", value="腺癌", unit="",
                 event_date="2023-07-01", layer="A")]
    passed, rej = run_safety_gate(ctx, rows)
    assert not passed

def test_tumor_marker_scan_rejected():
    ctx = _ctx()
    rows = [_row(ctx, category="检验", feature_name="CEA", value="5.2", unit="ng/mL",
                 event_date="2023-07-01", layer="A")]
    passed, rej = run_safety_gate(ctx, rows)
    assert not passed

def test_denial_term_scan_rejected():
    ctx = _ctx()
    rows = [_row(ctx, category="病程", feature_name="症状", value="新发高血压", unit="",
                 event_date="2023-07-01", layer="A")]
    passed, rej = run_safety_gate(ctx, rows)
    assert not passed

def test_denial_paren_history_conflict_rejected():
    # 病例 '否认高血压（史）' → 归一化否认项 '高血压'；
    # 噪声行 '新发高血压（史）' 命中否认冲突 → run_safety_gate 拒绝
    ev = [
        {"group_id":"g0","category":"入院","feature_name":"入院年龄","value":"66","event_date":"2023-03-01"},
        {"group_id":"g2","category":"病理","feature_name":"CEA","value":"3.1","event_date":"2023-07-02"},
        {"group_id":"gt","category":"评估","feature_name":"疗效评估","value":"PR","event_date":"2023-08-14"},
        {"group_id":"g4","category":"病史","feature_name":"既往史",
         "value":"否认高血压（史）","event_date":"2023-03-01"},
    ]
    ctx = build_context(case_id="c1", events=ev, task_type="T2_response",
                        target_group_id="gt", target_date="2023-08-14",
                        instruction="评估疗效", ground_truth={"response":"PR"})
    assert "高血压" in ctx.denial_terms  # 前提：否认项已归一化
    rows = [_row(ctx, category="病程", feature_name="症状", value="新发高血压（史）", unit="",
                 event_date="2023-07-01", layer="A")]
    passed, rej = run_safety_gate(ctx, rows)
    assert not passed
    assert any("否认冲突" in str(r.get("reason", "")) for r in rej)

def test_literal_leak_covers_noise():
    ctx = _ctx()  # instruction 不含答案；但噪声行直接写答案应被拒
    rows = [_row(ctx, category="病程", feature_name="病程",
                 value="疗效结论为PR，符合部分缓解", unit="", event_date="2023-07-01", layer="A")]
    passed, rej = run_safety_gate(ctx, rows)
    assert not passed  # value 含 GT 值 "PR" 且含疗效词

def test_row_text_joined():
    r = _row(_ctx(), category="检验", feature_name="白细胞计数", value="5.2",
             unit="×10^9/L", event_date="2023-07-01", layer="A")
    t = row_text(r)
    assert "白细胞计数" in t and "5.2" in t


def test_literal_leak_branch_clears_all(tmp_path):
    """直接覆盖 _literal_leak 清除分支：GT 值(len>=3)字面出现 → 清空全部行."""
    ev = [{"group_id":"g","category":"入院","feature_name":"x","value":"y","event_date":"2023-01-01"}]
    ctx = build_context(case_id="c1", events=ev, task_type="T2_response",
                        target_group_id="g", target_date="2023-03-01",
                        instruction="i", ground_truth={"response":"部分缓解"})  # GT len>=3
    rows = [_row(ctx, category="病程", feature_name="病程",
                 value="结论为部分缓解", unit="", event_date="2023-02-01", layer="A")]
    passed, rej = run_safety_gate(ctx, rows)
    assert passed == []
    assert any("leak" in str(r.get("reason", "")) or "GT值" in str(r.get("reason", "")) for r in rej)
