#!/usr/bin/env python3
"""Generate one reviewed oncology task from a LangGraph state."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from pipeline.oncology_generation.graph import run_generation
from pipeline.oncology_generation.leakage import find_leaked_target_values
from pipeline.oncology_generation.paths import safe_case_path
from agent.llm_client import LLMClient
from scripts.pipeline_env import load_model_env
from tools.csv_category_tools import CATEGORY_TOOL_SPECS


def export_task(state: dict[str, Any], output_root: Path, cleaned_root: Path) -> Path:
    task_id = str(state.get("case_id", ""))
    output_root = Path(output_root)
    task_dir = _task_dir(output_root, task_id)
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

    task_draft = state.get("task_draft", {})
    task_instruction = str(task_draft.get("instruction", "")).strip()
    role = str(task_draft.get("role", "肿瘤科医生")).strip() or "肿瘤科医生"
    if not task_instruction:
        raise ValueError("task draft has no instruction")
    normalized_instruction = task_instruction.casefold()
    if "ground_truth" in normalized_instruction or "pass_criteria" in normalized_instruction:
        raise ValueError("task instruction leaks evaluator fields")
    leaked_values = find_leaked_target_values(
        task_instruction,
        (event.get("value", "") for event in target_events if event.get("value", "")),
    )
    if leaked_values:
        raise ValueError(f"task instruction leaks target values: {leaked_values}")

    instruction = _compose_instruction(role, target_event_date, task_instruction)
    metadata = task_draft
    tags = metadata.get("tags", ["Oncology", "Diagnosis & Interpretation"])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError("task tags must be a list of strings")

    relative_data_root = Path(os.path.relpath(cleaned_root, start=task_dir)).as_posix()
    task_toml = (
        "[metadata]\n"
        f"case_id = {json.dumps(task_id, ensure_ascii=False)}\n"
        f"data_root = {json.dumps(relative_data_root, ensure_ascii=False)}\n"
        f"tags = {json.dumps(tags, ensure_ascii=False)}\n"
    )
    ground_truth = {
        "case_id": task_id,
        "target_group_id": target_group_id,
        "target_event_date": target_event_date,
        "source_rows": source_rows,
        "target_events": target_events,
    }

    output_root.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{task_id}.", dir=output_root))
    try:
        _write_task_files(staging_dir, instruction, task_toml, ground_truth)
        if not is_complete_task_dir(staging_dir, expected_case_id=task_id):
            raise ValueError("staged task does not satisfy the task contract")
        staging_dir.rename(task_dir)
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
    return task_dir


def _task_dir(output_root: Path, task_id: str) -> Path:
    try:
        return safe_case_path(output_root, task_id)
    except ValueError as exc:
        raise ValueError("state must contain a safe case_id") from exc


def _write_task_files(task_dir: Path, instruction: str, task_toml: str, ground_truth: dict[str, Any]) -> None:
    (task_dir / "instruction.md").write_text(instruction + "\n", encoding="utf-8")
    (task_dir / "task.toml").write_text(task_toml, encoding="utf-8")
    (task_dir / "ground_truth.json").write_text(
        json.dumps(ground_truth, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (task_dir / "tests").mkdir()
    (task_dir / "tests/test_outputs.py").write_text(_test_source(), encoding="utf-8")


def _compose_instruction(role: str, cutoff_date: str, task_instruction: str) -> str:
    return (
        f"你是一名{role}。\n\n"
        f"当前诊断时点：{cutoff_date}。\n"
        "你只能通过病例 CSV 查询工具访问该诊断时点之前已经公开的病例数据；"
        "诊断事件本身及其之后的数据不可访问。\n\n"
        f"任务：{task_instruction}\n\n"
        "请基于查询到的证据完成判断，并将最终结果保存为："
        "`output/diagnosis_report.md`。\n"
        "文件至少包含以下内容：诊断名称、诊断编码、分期系统及分期结果、诊断依据。"
    )


def is_complete_task_dir(task_dir: Path, expected_case_id: str | None = None) -> bool:
    task_dir = Path(task_dir)
    if not task_dir.is_dir():
        return False
    if {path.name for path in task_dir.iterdir()} != {"instruction.md", "task.toml", "ground_truth.json", "tests"}:
        return False
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir() or {path.name for path in tests_dir.iterdir()} != {"test_outputs.py"}:
        return False
    try:
        instruction = (task_dir / "instruction.md").read_text(encoding="utf-8").strip()
        metadata = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))["metadata"]
        ground_truth = json.loads((task_dir / "ground_truth.json").read_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError):
        return False
    case_id = expected_case_id or task_dir.name
    tags = metadata.get("tags") if isinstance(metadata, dict) else None
    data_root = metadata.get("data_root") if isinstance(metadata, dict) else None
    return bool(
        instruction
        and isinstance(metadata, dict)
        and metadata.get("case_id") == case_id
        and isinstance(data_root, str)
        and data_root
        and not Path(data_root).is_absolute()
        and isinstance(tags, list)
        and all(isinstance(tag, str) for tag in tags)
        and isinstance(ground_truth, dict)
        and ground_truth.get("case_id") == case_id
        and ground_truth.get("target_group_id")
        and ground_truth.get("target_event_date")
        and isinstance(ground_truth.get("source_rows"), list)
        and ground_truth["source_rows"]
        and isinstance(ground_truth.get("target_events"), list)
        and ground_truth["target_events"]
        and (tests_dir / "test_outputs.py").is_file()
    )


def _test_source() -> str:
    return '''import json
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
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id")
    parser.add_argument("--data-root", type=Path, default=Path("data/oncology_complete_trajectory"))
    parser.add_argument("--output-root", type=Path, default=Path("tasks/oncology-v1"))
    parser.add_argument("--model")
    args = parser.parse_args()
    model_env = load_model_env("GENERATION")
    client = LLMClient(
        model_id=args.model or model_env.model or "openai/gpt-5.5",
        api_key=model_env.api_key,
        base_url=model_env.base_url,
    )
    allowed_tools = {name for _, name, _ in CATEGORY_TOOL_SPECS}
    state = run_generation(args.case_id, args.data_root, client, allowed_tools)
    if state.get("validation_errors"):
        raise SystemExit("generation rejected: " + "; ".join(state["validation_errors"]))
    print(export_task(state, args.output_root, args.data_root / "cleaned"))


if __name__ == "__main__":
    main()
