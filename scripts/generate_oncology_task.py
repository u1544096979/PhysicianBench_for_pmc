#!/usr/bin/env python3
"""Generate one reviewed oncology task from a LangGraph state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pipeline.oncology_generation.graph import run_generation
from agent.llm_client import LLMClient
from tools.csv_category_tools import CATEGORY_TOOL_SPECS


def export_task(state: dict[str, Any], output_root: Path) -> Path:
    task_id = str(state.get("case_id", "")).strip()
    if not task_id or "/" in task_id or "\\" in task_id:
        raise ValueError("state must contain a safe case_id")
    task_dir = Path(output_root) / task_id
    if task_dir.exists():
        raise FileExistsError(f"approved task already exists: {task_dir}")
    instruction = str(state.get("task_draft", {}).get("instruction", "")).strip()
    if not instruction:
        raise ValueError("task draft has no instruction")
    lowered = instruction.lower()
    if "ground_truth" in lowered or "pass_criteria" in lowered:
        raise ValueError("task instruction leaks evaluator fields")
    task_dir.mkdir(parents=True)
    (task_dir / "instruction.md").write_text(instruction + "\n", encoding="utf-8")
    metadata = state.get("task_draft", {})
    tags = json.dumps(metadata.get("tags", ["Oncology", "CSV trajectory"]), ensure_ascii=False)
    (task_dir / "task.toml").write_text(f"[metadata]\ntags = {tags}\n", encoding="utf-8")
    ground_truth = {
        "case_id": task_id,
        "selected_segment": state.get("selected_segment", {}),
        "checkpoints": state.get("checkpoint_drafts", []),
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


def test_checkpoint_evidence_is_present():
    for checkpoint in GROUND_TRUTH["checkpoints"]:
        assert checkpoint["kind"] in {"retrieval", "reasoning", "documentation"}
        assert checkpoint["evidence_refs"]
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
    print(export_task(state, args.output_root))


if __name__ == "__main__":
    main()
