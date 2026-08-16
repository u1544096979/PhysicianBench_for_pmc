#!/usr/bin/env python3
"""Generate reviewed oncology tasks for every case, resuming per case."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

from agent.llm_client import LLMClient
from pipeline.oncology_generation.graph import run_generation
from pipeline.oncology_generation.review_queue import ReviewItem, append_review_item
from scripts.generate_oncology_task import export_task
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
    llm = client or LLMClient(model_id="openai/gpt-5.5")
    allowed_tools = {name for _, name, _ in CATEGORY_TOOL_SPECS}
    selected_case_ids = tuple(case_ids) if case_ids is not None else PILOT_CASE_IDS
    for case_id in selected_case_ids:
        summary.processed += 1
        if (output_root / case_id).exists():
            summary.exported += 1
            continue
        try:
            state = run_generation(case_id, data_root, llm, allowed_tools)
            if state.get("validation_errors"):
                raise ValueError("; ".join(state["validation_errors"]))
            export_task(state, output_root, data_root / "cleaned")
            summary.exported += 1
        except Exception as exc:
            summary.rejected += 1
            summary.review_queue += 1
            summary.errors[case_id] = str(exc)
            append_review_item(review_path, ReviewItem(case_id, [str(exc)], str(data_root / "generated" / case_id)))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data/oncology_complete_trajectory"))
    parser.add_argument("--output-root", type=Path, default=Path("tasks/oncology-v1"))
    parser.add_argument("--case-id", "--case-ids", nargs="+", dest="case_ids")
    args = parser.parse_args()
    print(generate_all_cases(args.data_root, args.output_root, case_ids=args.case_ids).__dict__)


if __name__ == "__main__":
    main()
