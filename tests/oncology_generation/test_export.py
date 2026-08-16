import json
import tomllib
from pathlib import Path

import pytest

from scripts.generate_oncology_task import export_task


def _state(cleaned_path: Path):
    return {
        "case_id": "case-1",
        "target_group_id": "g1",
        "target_events": [
            {
                "_source_row": "12",
                "case_id": "case-1",
                "group_id": "g1",
                "event_date": "2024-03-18",
                "category": "病理",
                "feature_name": "病理诊断",
                "value": "肺腺癌",
            },
            {
                "_source_row": "13",
                "case_id": "case-1",
                "group_id": "g1",
                "event_date": "2024-03-18",
                "category": "病理",
                "feature_name": "分期",
                "value": "IIIA",
            },
        ],
        "cleaned_path": cleaned_path,
        "task_draft": {
            "instruction": "Review the patient's oncology trajectory and write a concise assessment.",
            "tags": ["Oncology", "Diagnosis & Interpretation"],
        },
    }


def test_export_writes_task_contract(tmp_path: Path):
    output_root = tmp_path / "tasks" / "oncology-v1"
    cleaned_root = tmp_path / "data" / "oncology_complete_trajectory" / "cleaned"
    cleaned_path = cleaned_root / "case-1.csv"
    cleaned_path.parent.mkdir(parents=True)
    cleaned_path.write_text("case_id,group_id\ncase-1,g0\n", encoding="utf-8")

    task_dir = export_task(_state(cleaned_path), output_root, cleaned_root)

    assert {p.name for p in task_dir.iterdir()} == {"instruction.md", "task.toml", "ground_truth.json", "tests"}
    assert (task_dir / "tests/test_outputs.py").is_file()
    assert not (task_dir / "case-1.csv").exists()
    assert cleaned_path.is_file()

    ground_truth = json.loads((task_dir / "ground_truth.json").read_text())
    assert ground_truth == {
        "case_id": "case-1",
        "target_group_id": "g1",
        "target_event_date": "2024-03-18",
        "source_rows": ["12", "13"],
        "target_events": _state(cleaned_path)["target_events"],
    }
    assert "selected_segment" not in ground_truth
    assert "checkpoints" not in ground_truth

    metadata = tomllib.loads((task_dir / "task.toml").read_text())["metadata"]
    assert metadata["case_id"] == "case-1"
    assert metadata["data_root"] == "../../../data/oncology_complete_trajectory/cleaned"
    assert metadata["tags"] == ["Oncology", "Diagnosis & Interpretation"]
    assert "pass_criteria" not in (task_dir / "instruction.md").read_text()
    assert "肺腺癌" not in (task_dir / "instruction.md").read_text()


def test_export_refuses_overwrite_and_leakage(tmp_path: Path):
    cleaned_root = tmp_path / "cleaned"
    cleaned_path = cleaned_root / "case-1.csv"
    cleaned_root.mkdir()
    cleaned_path.write_text("case_id\ncase-1\n", encoding="utf-8")
    export_task(_state(cleaned_path), tmp_path / "tasks", cleaned_root)
    with pytest.raises(FileExistsError):
        export_task(_state(cleaned_path), tmp_path / "tasks", cleaned_root)
    bad = _state(cleaned_root / "case-2.csv")
    bad["cleaned_path"].write_text("case_id\ncase-2\n", encoding="utf-8")
    bad["case_id"] = "case-2"
    bad["task_draft"]["instruction"] = "Here are the ground_truth pass_criteria."
    with pytest.raises(ValueError, match="leaks"):
        export_task(bad, tmp_path / "tasks", cleaned_root)

    leaked_answer = _state(cleaned_root / "case-3.csv")
    leaked_answer["case_id"] = "case-3"
    leaked_answer["cleaned_path"].write_text("case_id\ncase-3\n", encoding="utf-8")
    leaked_answer["task_draft"]["instruction"] = "The diagnosis is 肺腺癌."
    with pytest.raises(ValueError, match="target values"):
        export_task(leaked_answer, tmp_path / "tasks", cleaned_root)


def test_export_requires_langgraph_materialized_cleaned_csv(tmp_path: Path):
    cleaned_root = tmp_path / "cleaned"
    cleaned_root.mkdir()
    state = _state(cleaned_root / "case-1.csv")

    with pytest.raises(ValueError, match="materialized cleaned CSV"):
        export_task(state, tmp_path / "tasks", cleaned_root)


def test_export_rejects_case_insensitive_target_value_leakage(tmp_path: Path):
    cleaned_root = tmp_path / "cleaned"
    cleaned_path = cleaned_root / "case-1.csv"
    cleaned_root.mkdir()
    cleaned_path.write_text("case_id\ncase-1\n", encoding="utf-8")
    state = _state(cleaned_path)
    state["task_draft"]["instruction"] = "The likely stage is iiia."

    with pytest.raises(ValueError, match="target values"):
        export_task(state, tmp_path / "tasks", cleaned_root)
