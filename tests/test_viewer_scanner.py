"""viewer.scanner 纯函数单测：tmp_path 构造假任务树。

覆盖:正常 run、缺 scorecard 的 run、坏 JSONL 行、无 run 的 case。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from viewer import scanner  # noqa: E402


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _task_toml(case_id: str, label: str, ttype: str) -> str:
    return (
        f'case_id = "{case_id}"\n'
        f'task_type = "{ttype}"\n'
        f'task_label = "{label}"\n'
        f'target_date = "2023-08-14"\n'
        f'deliverable = "output/diagnosis_report.md"\n'
        f'data_file = "cleaned_trajectory.csv"\n'
    )


def _make_tree(root: Path) -> Path:
    """构造 2 个 case：caseAAA(两个 run)+caseBBB(无 run)。"""
    c1 = root / "caseAAA"
    _write(c1 / "task.toml", _task_toml("caseAAA", "疗效评估", "T2_response"))
    _write(c1 / "instruction.md", "# 请你判断疗效\n\n正文")
    _write(c1 / "checkpoints.json", json.dumps(
        {"checkpoints": [{"checkpoint_id": "c1", "layer": "data_retrieval", "description": "查询影像",
                          "eval_method": "llm_judge", "params": {}}]}, ensure_ascii=False))
    _write(c1 / "ground_truth.json", json.dumps({"response": "PR"}, ensure_ascii=False))
    _write(c1 / "cleaned_trajectory.csv", "col1,col2\nv1,v2\n")

    # 完整 run（含一条坏 JSONL 行，应被跳过）
    r1 = c1 / "runs" / "20260101-000000"
    _write(r1 / "scorecard.json", json.dumps({
        "agent_model": "m1", "tool_calls": 3,
        "checkpoint_summary": {"total": 2, "pass": 2, "fail": 0, "score": 1.0},
        "checkpoints": [{"checkpoint_id": "c1", "layer": "x", "verdict": "pass", "judge": "code", "comment": "ok"}],
    }, ensure_ascii=False))
    _write(r1 / "trajectory.json",
        '{"type": "instruction", "timestamp": "2026-01-01T00:00:00"}\n'
        '{"type": "tool_call", "timestamp": "2026-01-01T00:00:02", "metadata": {"tool_name": "query_imaging"}}\n'
        'THIS-IS-NOT-JSON\n'
        '{"type": "final_result", "timestamp": "2026-01-01T00:00:05"}\n')
    _write(r1 / "output" / "diagnosis_report.md", "# 报告标题\n\n正文段落")

    # 缺 scorecard 的 run（模拟中断/崩溃）
    r2 = c1 / "runs" / "20260102-000000"
    _write(r2 / "trajectory.json",
        '{"type": "instruction", "timestamp": "2026-01-02T00:00:00"}\n'
        '{"type": "tool_call", "timestamp": "2026-01-02T00:00:01", "metadata": {"tool_name": "x"}}\n'
        '{"type": "final_result", "timestamp": "2026-01-02T00:00:03"}\n')

    # 无 run 的 case
    c2 = root / "caseBBB"
    _write(c2 / "task.toml", _task_toml("caseBBB", "分期", "T1_staging"))
    return root


def test_scan_tasks(tmp_path):
    _make_tree(tmp_path)
    tasks = scanner.scan_tasks(tmp_path)
    by_id = {t.case_id: t for t in tasks}
    assert set(by_id) == {"caseAAA", "caseBBB"}
    a = by_id["caseAAA"]
    assert a.task_label == "疗效评估"
    assert a.task_type == "T2_response"
    assert a.target_date == "2023-08-14"
    assert a.run_count == 2
    assert a.best_score == 1.0
    b = by_id["caseBBB"]
    assert b.run_count == 0
    assert b.best_score is None


def test_load_task(tmp_path):
    _make_tree(tmp_path)
    det = scanner.load_task(tmp_path, "caseAAA")
    assert det.task_label == "疗效评估"
    assert "疗效" in det.instruction_md
    assert "<h1>" in det.instruction_html
    assert det.checkpoints[0]["checkpoint_id"] == "c1"
    assert len(det.runs) == 2
    assert det.has_ground_truth is True
    assert det.has_cleaned_csv is True


def test_load_run_complete(tmp_path):
    _make_tree(tmp_path)
    rd = scanner.load_run(tmp_path, "caseAAA", "20260101-000000")
    assert rd.has_scorecard is True
    assert rd.status == "complete"
    assert rd.agent_model == "m1"
    assert rd.tool_calls == 3
    assert rd.checkpoint_summary["pass"] == 2
    assert rd.duration_seconds == 5.0
    assert len(rd.events) == 3
    assert rd.failed_lines == 1
    assert rd.events[0]["type"] == "instruction"
    assert "<h1>" in rd.report_html
    assert rd.ground_truth == {"response": "PR"}
    assert "<table>" in rd.cleaned_csv_html


def test_load_run_incomplete(tmp_path):
    _make_tree(tmp_path)
    rd = scanner.load_run(tmp_path, "caseAAA", "20260102-000000")
    assert rd.has_scorecard is False
    assert rd.status == "incomplete"
    assert rd.scorecard is None
    assert rd.agent_model is None
    assert rd.tool_calls is None
    assert len(rd.events) == 3
    assert rd.duration_seconds == 3.0


def test_load_run_skips_valid_non_dict_lines(tmp_path):
    """合法 JSON 但非 dict 的行（null/list/str）：跳过且不进 failed_lines；真坏行（JSONDecodeError）才计数。"""
    _write(tmp_path / "caseXXX" / "task.toml", _task_toml("caseXXX", "X", "T1"))
    run_dir = tmp_path / "caseXXX" / "runs" / "r1"
    _write(run_dir / "trajectory.json",
        'null\n'
        '[1, 2]\n'
        '"str"\n'
        '{"type": "instruction", "timestamp": "2026-01-01T00:00:00"}\n'
        'BAD\n')
    rd = scanner.load_run(tmp_path, "caseXXX", "r1")
    assert [e["type"] for e in rd.events] == ["instruction"]
    assert rd.failed_lines == 1


def test_load_task_missing_task_toml_raises_value_error(tmp_path):
    _write(tmp_path / "caseNoToml" / "instruction.md", "# x")
    with pytest.raises(ValueError, match="task.toml"):
        scanner.load_task(tmp_path, "caseNoToml")


def test_load_task_invalid_task_toml_raises_value_error(tmp_path):
    _write(tmp_path / "caseBadToml" / "task.toml", 'case_id = "caseBadToml"\ntask_type = [broken\n')
    with pytest.raises(ValueError, match="task.toml"):
        scanner.load_task(tmp_path, "caseBadToml")


def test_load_run_missing_dir_returns_empty(tmp_path):
    _make_tree(tmp_path)
    rd = scanner.load_run(tmp_path, "caseBBB", "nonexistent")
    assert rd.events == []
    assert rd.has_scorecard is False
    assert rd.report_html == ""
    assert rd.cleaned_csv_html == ""


def test_run_summaries_sorted(tmp_path):
    _make_tree(tmp_path)
    det = scanner.load_task(tmp_path, "caseAAA")
    assert [r.run_id for r in det.runs] == ["20260101-000000", "20260102-000000"]
    assert det.runs[0].status == "complete"
    assert det.runs[1].status == "incomplete"
