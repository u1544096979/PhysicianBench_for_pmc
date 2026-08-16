#!/usr/bin/env python3
"""
Evaluation runner for a single task.

Reads the test file at <task_folder>/tests/test_outputs.py and runs it via
pytest. The test file derives output/trajectory paths from the JOB_DIR env
var (set here from --job-dir) with a fallback to the in-task layout.

Usage:
    python scripts/run_eval.py <task_folder> [--job-dir DIR]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.llm_client import LLMClient
from scripts.pipeline_env import load_model_env
from utils.diagnosis_eval import (
    JudgeParseError,
    evaluate_diagnosis_judge,
    evaluate_diagnosis_rules,
)


DEFAULT_EVAL_MODEL = "openai/gpt-5.5"


def _read_agent_final_output(job_dir: Path) -> str:
    stdout_path = job_dir / "logs" / "agent" / "stdout.txt"
    if stdout_path.is_file():
        stdout = stdout_path.read_text(encoding="utf-8").strip()
        if stdout:
            return stdout

    output_dir = job_dir / "workspace" / "output"
    output_parts = []
    if output_dir.is_dir():
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                output_parts.append(path.read_text(encoding="utf-8", errors="replace"))
    final_output = "\n\n".join(part for part in output_parts if part.strip()).strip()
    if not final_output:
        raise FileNotFoundError("Agent final output was not found")
    return final_output


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary_path = Path(temporary_file.name)
    try:
        with temporary_file:
            temporary_file.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_diagnosis_evaluation(
    task_dir: Path,
    job_dir: Path,
    client: Any | None = None,
) -> Path:
    """Evaluate one agent output and persist rule/judge results."""
    output_path = job_dir / "logs" / "verifier" / "diagnosis_eval.json"
    payload: dict[str, Any] = {
        "rule": None,
        "judge": None,
        "evaluator_error": None,
    }
    try:
        ground_truth = json.loads((task_dir / "ground_truth.json").read_text(encoding="utf-8"))
        target_events = ground_truth["target_events"]
        if not isinstance(target_events, list):
            raise ValueError("ground_truth.target_events must be a list")
        agent_text = _read_agent_final_output(job_dir)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        payload["evaluator_error"] = {"stage": "input", "message": str(exc)}
        _write_json(output_path, payload)
        return output_path

    payload["rule"] = evaluate_diagnosis_rules(agent_text, target_events)
    try:
        if client is None:
            model_env = load_model_env("AGENT_EVAL")
            client = LLMClient(
                model_id=model_env.model or DEFAULT_EVAL_MODEL,
                api_key=model_env.api_key,
                base_url=model_env.base_url,
            )
        payload["judge"] = evaluate_diagnosis_judge(agent_text, target_events, client)
    except JudgeParseError as exc:
        payload["evaluator_error"] = {"stage": "judge_parse", "message": str(exc)}
    except Exception as exc:
        payload["evaluator_error"] = {"stage": "judge_call", "message": str(exc)}

    _write_json(output_path, payload)
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run evaluation for a single task")
    parser.add_argument("task_folder", help="Path to task folder")
    parser.add_argument(
        "--job-dir",
        help="Per-task job directory (provides workspace/ and logs/). "
             "If omitted, the test file falls back to the in-task layout.",
    )
    args = parser.parse_args(argv)

    task_dir = Path(args.task_folder).resolve()
    test_path = task_dir / "tests" / "test_outputs.py"

    if not test_path.exists():
        print(f"No test file at {test_path}")
        return 0

    job_dir = Path(args.job_dir).resolve() if args.job_dir else None

    print(f"Running tests: {test_path}")
    print("Backend:       oncology CSV")
    print(f"Job dir:       {job_dir or '(fallback to in-task layout)'}")
    print()

    env = dict(os.environ)
    if job_dir:
        env["JOB_DIR"] = str(job_dir)
        cwd = job_dir / "workspace"
        cwd.mkdir(parents=True, exist_ok=True)
    else:
        cwd = task_dir / "workspace"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_path), "-v", "--tb=short", "-rA"],
        cwd=str(cwd),
        env=env,
    )
    ground_truth_path = task_dir / "ground_truth.json"
    evaluator_passed = True
    if ground_truth_path.is_file():
        artifact_root = job_dir or task_dir
        diagnosis_path = write_diagnosis_evaluation(task_dir, artifact_root)
        diagnosis_payload = json.loads(diagnosis_path.read_text(encoding="utf-8"))
        print(f"Diagnosis eval: {diagnosis_path}")
        if diagnosis_payload["evaluator_error"]:
            print(f"Evaluator error: {diagnosis_payload['evaluator_error']}")
        evaluator_passed = (
            diagnosis_payload["evaluator_error"] is None
            and diagnosis_payload.get("rule", {}).get("label") == "correct"
            and diagnosis_payload.get("judge", {}).get("label") == "correct"
        )
        if not evaluator_passed:
            print("Diagnosis evaluator did not pass")
    if result.returncode != 0:
        return result.returncode
    return 0 if evaluator_passed else 1


if __name__ == "__main__":
    sys.exit(main())
