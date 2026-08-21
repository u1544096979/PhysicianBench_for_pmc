# tests/test_noise_apply_cli.py
from __future__ import annotations
import sys, json
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import scripts.apply_noise as AP


def test_parse_args_defaults():
    args = AP.parse_args(["--dry-run"])
    assert args.dry_run is True and args.resume is False
    assert args.workers == 1


def test_select_task_ids(tmp_path):
    root = tmp_path / "tasks" / "oncology-v2"
    for cid in ("a", "b"):
        (root / cid).mkdir(parents=True)
        (root / cid / "task.toml").write_text("")
    ids = AP.select_task_ids(root, case_ids=None, limit=1)
    assert ids == ["a"]  # 排序后取前1


def test_process_case_stub_calls_monkeypatched():
    pass  # 端到端在 Task 11 集成测试覆盖
