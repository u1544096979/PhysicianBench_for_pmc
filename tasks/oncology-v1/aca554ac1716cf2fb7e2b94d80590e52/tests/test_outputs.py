import json
from pathlib import Path

from utils.eval_helpers import read_output_file

TASK_DIR = Path(__file__).parent.parent
GROUND_TRUTH = json.loads((TASK_DIR / "ground_truth.json").read_text())


def test_documentation_output_exists():
    report = Path.cwd() / "output" / "diagnosis_report.md"
    assert report.is_file(), "Agent did not produce output/diagnosis_report.md"
    assert report.read_text(encoding="utf-8").strip(), "Diagnosis report is empty"


def test_ground_truth_retains_source_events():
    assert GROUND_TRUTH["target_group_id"]
    assert GROUND_TRUTH["target_events"]
    assert GROUND_TRUTH["source_rows"]
    assert all(event["feature_name"] for event in GROUND_TRUTH["target_events"])
    assert all(event["value"] for event in GROUND_TRUTH["target_events"])
