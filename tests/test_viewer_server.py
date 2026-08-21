"""viewer.server FastAPI API 测试：3 个 API 成功路径 + 404。

用 tmp_path 构造假任务树（与 scanner 测试同一套，这里内联复刻）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from viewer.server import create_app  # noqa: E402


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_tree(root: Path) -> Path:
    c1 = root / "caseAAA"
    _write(c1 / "task.toml",
        'case_id = "caseAAA"\ntask_type = "T2_response"\ntask_label = "疗效评估"\n'
        'target_date = "2023-08-14"\ndeliverable = "output/diagnosis_report.md"\n'
        'data_file = "cleaned_trajectory.csv"\n')
    _write(c1 / "instruction.md", "# 请你判断疗效\n\n正文")
    _write(c1 / "checkpoints.json", json.dumps(
        {"checkpoints": [{"checkpoint_id": "c1"}]}, ensure_ascii=False))
    _write(c1 / "ground_truth.json", json.dumps({"response": "PR"}, ensure_ascii=False))
    _write(c1 / "cleaned_trajectory.csv", "col1,col2\nv1,v2\n")
    r1 = c1 / "runs" / "20260101-000000"
    _write(r1 / "scorecard.json", json.dumps({
        "agent_model": "m1", "tool_calls": 3,
        "checkpoint_summary": {"total": 2, "pass": 2, "score": 1.0},
        "checkpoints": [{"checkpoint_id": "c1", "verdict": "pass"}],
    }, ensure_ascii=False))
    _write(r1 / "trajectory.json",
        '{"type": "instruction", "timestamp": "2026-01-01T00:00:00"}\n'
        'BAD\n'
        '{"type": "final_result", "timestamp": "2026-01-01T00:00:05"}\n')
    _write(r1 / "output" / "diagnosis_report.md", "# 报告标题\n\n正文")
    c2 = root / "caseBBB"
    _write(c2 / "task.toml",
        'case_id = "caseBBB"\ntask_type = "T1_staging"\ntask_label = "分期"\n'
        'target_date = "2023-08-14"\ndeliverable = "output/diagnosis_report.md"\n'
        'data_file = "cleaned_trajectory.csv"\n')
    return root


@pytest.fixture()
def client(tmp_path):
    _make_tree(tmp_path)
    return TestClient(create_app(root=tmp_path))


def test_list_tasks(client):
    r = client.get("/api/tasks")
    assert r.status_code == 200
    body = r.json()
    ids = {t["case_id"] for t in body}
    assert ids == {"caseAAA", "caseBBB"}
    a = next(t for t in body if t["case_id"] == "caseAAA")
    assert a["run_count"] == 1
    assert a["best_score"] == 1.0


def test_task_detail(client):
    r = client.get("/api/tasks/caseAAA")
    assert r.status_code == 200
    body = r.json()
    assert body["case_id"] == "caseAAA"
    assert body["instruction_md"] != ""
    assert len(body["runs"]) == 1
    assert body["runs"][0]["run_id"] == "20260101-000000"
    assert body["has_ground_truth"] is True


def test_run_detail(client):
    r = client.get("/api/tasks/caseAAA/runs/20260101-000000")
    assert r.status_code == 200
    body = r.json()
    assert body["tool_calls"] == 3
    assert len(body["events"]) == 2
    assert body["failed_lines"] == 1
    assert "<table>" in body["cleaned_csv_html"]
    assert body["ground_truth"] == {"response": "PR"}


def test_case_without_task_toml_404(client, tmp_path):
    """游离目录（存在但缺 task.toml）：直接 URL 访问应 404 而非 500。"""
    _write(tmp_path / "caseNoToml" / "instruction.md", "# x")
    r = client.get("/api/tasks/caseNoToml")
    assert r.status_code == 404
    assert "task.toml" in r.json()["detail"]


def test_unknown_case_404(client):
    r = client.get("/api/tasks/nope")
    assert r.status_code == 404
    assert r.json()["detail"]


def test_unknown_run_404(client):
    r = client.get("/api/tasks/caseAAA/runs/nope")
    assert r.status_code == 404
    assert r.json()["detail"]
