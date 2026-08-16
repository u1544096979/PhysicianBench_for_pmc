import json
from pathlib import Path

import pytest

from scripts.generate_oncology_task import export_task


def _state():
    return {
        "case_id": "case-1",
        "target_group_id": "g1",
        "target_events": [],
        "task_draft": {"instruction": "Review the patient's oncology trajectory and write a concise assessment."},
    }


def test_export_writes_task_contract(tmp_path: Path):
    task_dir = export_task(_state(), tmp_path)
    assert {p.name for p in task_dir.iterdir()} == {"instruction.md", "task.toml", "ground_truth.json", "tests"}
    assert (task_dir / "tests/test_outputs.py").is_file()
    assert json.loads((task_dir / "ground_truth.json").read_text())["case_id"] == "case-1"
    assert "pass_criteria" not in (task_dir / "instruction.md").read_text()


def test_export_refuses_overwrite_and_leakage(tmp_path: Path):
    export_task(_state(), tmp_path)
    with pytest.raises(FileExistsError):
        export_task(_state(), tmp_path)
    bad = _state()
    bad["case_id"] = "case-2"
    bad["task_draft"]["instruction"] = "Here are the ground_truth pass_criteria."
    with pytest.raises(ValueError, match="leaks"):
        export_task(bad, tmp_path)
