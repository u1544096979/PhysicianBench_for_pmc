#!/usr/bin/env python3
"""Generate reviewed oncology tasks for every case, resuming per case."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from agent.llm_client import LLMClient
from pipeline.oncology_generation.graph import run_generation
from pipeline.oncology_generation.paths import safe_case_path
from pipeline.oncology_generation.review_queue import ReviewItem, append_review_item
from scripts.generate_oncology_task import export_task, is_complete_task_dir
from scripts.pipeline_env import load_model_env
from tools.csv_category_tools import CATEGORY_TOOL_SPECS

PILOT_CASE_IDS = (
    "71af50c891bd0e80cd017c8beb2bb446",
    "15c35bb60e48e62f9beb9fd127248e03",
    "7df4bd9af484dcec897b2f2726e01db2",
    "01864b911256ca7332f7974165d7aeb8",
    "aca554ac1716cf2fb7e2b94d80590e52",
)


@dataclass
class BatchSummary:
    processed: int = 0
    exported: int = 0
    rejected: int = 0
    review_queue: int = 0
    errors: dict[str, str] = field(default_factory=dict)


def generate_all_cases(
    data_root: Path,
    output_root: Path,
    max_workers: int = 1,
    client=None,
    case_ids: list[str] | tuple[str, ...] | None = None,
) -> BatchSummary:
    if max_workers != 1:
        raise ValueError("parallel generation is not enabled until sequential output is verified")
    summary = BatchSummary()
    review_path = data_root / "generated" / "review_queue.jsonl"
    model_env = load_model_env("GENERATION")
    llm = client or LLMClient(
        model_id=model_env.model or "openai/gpt-5.5",
        api_key=model_env.api_key,
        base_url=model_env.base_url,
    )
    allowed_tools = {name for _, name, _ in CATEGORY_TOOL_SPECS}
    selected_case_ids = tuple(case_ids) if case_ids is not None else PILOT_CASE_IDS
    for case_id in selected_case_ids:
        summary.processed += 1
        try:
            task_dir = safe_case_path(output_root, case_id)
            if is_complete_task_dir(task_dir, expected_case_id=case_id):
                summary.exported += 1
                continue
            state = run_generation(case_id, data_root, llm, allowed_tools)
            if state.get("validation_errors"):
                raise ValueError("; ".join(state["validation_errors"]))
            export_task(state, output_root, data_root / "cleaned")
            summary.exported += 1
        except Exception as exc:
            summary.rejected += 1
            errors = [str(exc)]
            state_path = data_root / "generated" / "_unavailable_state.json"
            try:
                state_path = _failure_state_path(data_root, case_id)
                _persist_failure_state(state_path, case_id, exc)
            except Exception as state_exc:
                errors.append(f"state persistence failed: {state_exc}")
            try:
                append_review_item(review_path, ReviewItem(case_id, list(errors), str(state_path)))
                summary.review_queue += 1
            except Exception as review_exc:
                errors.append(f"review queue append failed: {review_exc}")
            summary.errors[case_id] = "; ".join(errors)
    return summary


def _failure_state_path(data_root: Path, case_id: str) -> Path:
    generated_root = data_root / "generated"
    try:
        case_root = safe_case_path(generated_root, case_id)
    except ValueError:
        digest = hashlib.sha256(str(case_id).encode("utf-8")).hexdigest()[:16]
        case_root = generated_root / "_invalid_case_ids" / digest
    state_path = case_root / "state.json"
    state_path.resolve().relative_to(generated_root.resolve())
    return state_path


def _persist_failure_state(state_path: Path, case_id: str, error: Exception) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {"case_id": case_id, "error": str(error), "review_status": "needs_revision"}
    temporary_path = state_path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(state_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data/oncology_complete_trajectory"))
    parser.add_argument("--output-root", type=Path, default=Path("tasks/oncology-v1"))
    parser.add_argument("--case-id", "--case-ids", nargs="+", dest="case_ids")
    args = parser.parse_args()
    print(generate_all_cases(args.data_root, args.output_root, case_ids=args.case_ids).__dict__)


if __name__ == "__main__":
    main()
