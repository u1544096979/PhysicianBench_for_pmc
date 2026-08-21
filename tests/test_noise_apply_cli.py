# tests/test_noise_apply_cli.py
from __future__ import annotations
import sys
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


def test_is_completed_noisy(tmp_path):
    noise_dir = tmp_path / "case"
    noise_dir.mkdir()
    manifest = noise_dir / "noise_manifest.json"
    # 无 manifest -> 不视为已完成
    assert AP._is_completed_noisy(noise_dir) is False
    # degraded_clean -> 不跳过（重试）
    manifest.write_text('{"final_status": "degraded_clean"}', encoding="utf-8")
    assert AP._is_completed_noisy(noise_dir) is False
    # noisy -> 已完成，可跳过
    manifest.write_text('{"final_status": "noisy"}', encoding="utf-8")
    assert AP._is_completed_noisy(noise_dir) is True
    # 损坏的 manifest -> 不跳过（重试）
    manifest.write_text("{not json", encoding="utf-8")
    assert AP._is_completed_noisy(noise_dir) is False
