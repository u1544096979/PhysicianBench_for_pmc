#!/usr/bin/env python3
"""Generate one reviewed oncology task from a LangGraph state."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from pipeline.oncology_generation.graph import run_generation
from agent.llm_client import LLMClient
from tools.csv_category_tools import CATEGORY_TOOL_SPECS


def export_task(state: dict[str, Any], output_root: Path, cleaned_root: Path) -> Path:
    task_id = str(state.get("case_id", "")).strip()
    if not task_id or "/" in task_id or "\\" in task_id:
        raise ValueError("state must contain a safe case_id")
    task_dir = Path(output_root) / task_id
    if task_dir.exists():
        raise FileExistsError(f"approved task already exists: {task_dir}")

    cleaned_root = Path(cleaned_root)
    cleaned_path = Path(state.get("cleaned_path", ""))
    expected_cleaned_path = cleaned_root / f"{task_id}.csv"
    if not cleaned_path.is_file() or cleaned_path.resolve() != expected_cleaned_path.resolve():
        raise ValueError(f"state must reference the materialized cleaned CSV: {expected_cleaned_path}")

    target_group_id = str(state.get("target_group_id", "")).strip()
    target_events = state.get("target_events", [])
    if not target_group_id or not isinstance(target_events, list) or not target_events:
        raise ValueError("state must contain a target group and its events")
    if any(str(event.get("group_id", "")) != target_group_id for event in target_events):
        raise ValueError("target events must all belong to target_group_id")
    source_rows = [str(event.get("_source_row", "")).strip() for event in target_events]
    if any(not source_row for source_row in source_rows):
        raise ValueError("target events must retain source row references")
    target_event_date = str(target_events[0].get("event_date", "")).strip()
    if not target_event_date:
        raise ValueError("target events must retain the target date")

    instruction = str(state.get("task_draft", {}).get("instruction", "")).strip()
    if not instruction:
        raise ValueError("task draft has no instruction")
    normalized_instruction = instruction.casefold()
    if "ground_truth" in normalized_instruction or "pass_criteria" in normalized_instruction:
        raise ValueError("task instruction leaks evaluator fields")
    leaked_values = [
        str(event.get("value", ""))
        for event in target_events
        if str(event.get("value", ""))
        and str(event.get("value", "")).casefold() in normalized_instruction
    ]
    if leaked_values:
        raise ValueError(f"task instruction leaks target values: {leaked_values}")

    task_dir.mkdir(parents=True)
    (task_dir / "instruction.md").write_text(instruction + "\n", encoding="utf-8")
    metadata = state.get("task_draft", {})
    tags = json.dumps(metadata.get("tags", ["Oncology", "Diagnosis & Interpretation"]), ensure_ascii=False)
    relative_data_root = Path(os.path.relpath(cleaned_root, start=task_dir)).as_posix()
    task_toml = (
        "[metadata]\n"
        f"case_id = {json.dumps(task_id, ensure_ascii=False)}\n"
        f"data_root = {json.dumps(relative_data_root, ensure_ascii=False)}\n"
        f"tags = {tags}\n"
    )
    (task_dir / "task.toml").write_text(task_toml, encoding="utf-8")
    ground_truth = {
        "case_id": task_id,
        "target_group_id": target_group_id,
        "target_event_date": target_event_date,
        "source_rows": source_rows,
        "target_events": target_events,
    }
    (task_dir / "ground_truth.json").write_text(json.dumps(ground_truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (task_dir / "tests").mkdir()
    (task_dir / "tests/test_outputs.py").write_text(_test_source(), encoding="utf-8")
    return task_dir


def _test_source() -> str:
    return '''import json
from pathlib import Path

from utils.eval_helpers import read_output_file

TASK_DIR = Path(__file__).parent.parent
GROUND_TRUTH = json.loads((TASK_DIR / "ground_truth.json").read_text())


def test_documentation_output_exists():
    output = list((Path.cwd() / "output").glob("*"))
    assert output, "Agent did not produce a deliverable in workspace/output"


def test_ground_truth_retains_source_events():
    assert GROUND_TRUTH["target_group_id"]
    assert GROUND_TRUTH["target_events"]
    assert GROUND_TRUTH["source_rows"]
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id")
    parser.add_argument("--data-root", type=Path, default=Path("data/oncology_complete_trajectory"))
    parser.add_argument("--output-root", type=Path, default=Path("tasks/oncology-v1"))
    parser.add_argument("--model", default="openai/gpt-5.5")
    args = parser.parse_args()
    client = LLMClient(model_id=args.model)
    allowed_tools = {name for _, name, _ in CATEGORY_TOOL_SPECS}
    state = run_generation(args.case_id, args.data_root, client, allowed_tools)
    if state.get("validation_errors"):
        raise SystemExit("generation rejected: " + "; ".join(state["validation_errors"]))
    print(export_task(state, args.output_root, args.data_root / "cleaned"))


if __name__ == "__main__":
    main()
