#!/usr/bin/env python3
"""
PhysicianBench local CSV task runner — runs a single task end-to-end.

Uses only the cleaned oncology CSV directory, runs the agent, then evaluates
the task via pytest. No Docker or FHIR service is started.
All run artifacts (workspace, logs, eval output, metadata) are written into
a per-task job directory at jobs/<batch>/<task>/. The task source folder
is never modified.

Flow:
  1. Resolve the read-only cleaned CSV directory
  2. Run the agent (writes to job_dir/workspace and job_dir/logs/agent)
  3. Run pytest evaluation (writes to job_dir/logs/verifier)
  4. Write metadata.json into job_dir

Usage:
    python scripts/run_task.py tasks/oncology-v1/<case_id> \\
        --model openai/gpt-5.5 --reasoning-effort high

    python scripts/run_task.py tasks/oncology-v1/<case_id> \\
        --skip-agent     # eval only (re-grade an existing job dir)

    python scripts/run_task.py tasks/oncology-v1/<case_id> \\
        --data-root data/oncology_complete_trajectory
"""

import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_MODEL = "openai/gpt-5.5"
DEFAULT_DATA_ROOT = REPO_ROOT / "data" / "oncology_complete_trajectory"
OPENROUTER_CREDITS_URL = "https://openrouter.ai/api/v1/credits"


# ---------------------------------------------------------------------------
# Cost tracking (optional)
# ---------------------------------------------------------------------------

def get_openrouter_usage() -> float | None:
    """Query OpenRouter credits API and return total_usage in dollars."""
    import urllib.request
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None
    try:
        req = urllib.request.Request(
            OPENROUTER_CREDITS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return float(data["data"]["total_usage"])
    except Exception as e:
        print(f"  WARNING: Could not fetch OpenRouter usage: {e}")
        return None


# ---------------------------------------------------------------------------
# Agent + eval invocations
# ---------------------------------------------------------------------------

def prepare_workspace(job_dir: Path, task_dir: Path) -> Path:
    """Create the agent's workspace inside job_dir/workspace.

    Symlinks task_dir/input_files into the workspace if present.
    """
    workspace = job_dir / "workspace"
    (workspace / "output").mkdir(parents=True, exist_ok=True)

    env_inputs = task_dir / "input_files"
    workspace_inputs = workspace / "input_files"
    if env_inputs.exists() and not workspace_inputs.exists():
        workspace_inputs.symlink_to(env_inputs.resolve())

    return workspace


def resolve_cleaned_data_root(data_root: Path) -> Path:
    """Resolve cleaned CSV data without allowing a symlink boundary escape."""
    dataset_root = Path(data_root).resolve()
    cleaned_root = (dataset_root / "cleaned").resolve()
    try:
        cleaned_root.relative_to(dataset_root)
    except ValueError as exc:
        raise ValueError("cleaned data root is outside oncology data root") from exc
    if not cleaned_root.is_dir():
        raise FileNotFoundError(f"Cleaned oncology CSV directory not found: {cleaned_root}")
    return cleaned_root


def validate_oncology_task_contract(task_dir: Path, cleaned_root: Path) -> str:
    """Validate that a task explicitly targets one cleaned oncology case."""
    task_toml = task_dir / "task.toml"
    if not task_toml.is_file():
        raise ValueError(f"Oncology task contract missing: {task_toml}")
    try:
        metadata = tomllib.loads(task_toml.read_text(encoding="utf-8"))["metadata"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Invalid oncology task contract: {task_toml}") from exc

    case_id = metadata.get("case_id") if isinstance(metadata, dict) else None
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("Oncology task metadata.case_id is required")
    if case_id != case_id.strip() or Path(case_id).name != case_id or Path(case_id).suffix:
        raise ValueError(f"Invalid oncology task case_id: {case_id!r}")
    if task_dir.name != case_id:
        raise ValueError(
            f"Oncology task directory name must match metadata.case_id: {case_id!r}"
        )

    configured_data_root = metadata.get("data_root")
    if not isinstance(configured_data_root, str) or not configured_data_root:
        raise ValueError("Oncology task metadata.data_root is required")
    if Path(configured_data_root).is_absolute():
        raise ValueError("Oncology task metadata.data_root must be relative")
    if (task_dir / configured_data_root).resolve() != cleaned_root.resolve():
        raise ValueError("Oncology task metadata.data_root must resolve to the cleaned data root")

    from data.oncology_complete_trajectory.index.build_index import load_case_csv

    try:
        load_case_csv(case_id, cleaned_root)
    except KeyError as exc:
        raise ValueError(f"Cleaned oncology CSV missing for case_id {case_id!r}") from exc
    return case_id


def run_agent(
    task_dir: Path, job_dir: Path, model: str | None, max_steps: int,
    temperature: float | None, parallel_tool_calls: bool, reasoning_effort: str | None,
    data_root: Path,
) -> bool:
    """Run the mini agent in-process. All outputs land under job_dir."""
    print("[3/4] Running agent...")
    workspace = prepare_workspace(job_dir, task_dir)

    instruction = (task_dir / "instruction.md").read_text()
    instruction = instruction.replace("/workspace/", f"{workspace}/")
    instruction += (
        f"\n\n## Working Directory\n\n"
        f"Your working directory is: {workspace}\n"
        f"Output files should be saved under: {workspace / 'output'}/\n"
    )

    from agent.llm_client import LLMClient
    from agent.mini_agent import MiniAgent
    from agent.tool_registry import ToolRegistry, register_all_tools
    from agent.trajectory import TrajectoryLogger
    from scripts.pipeline_env import load_model_env

    agent_log_dir = job_dir / "logs" / "agent"
    agent_log_dir.mkdir(parents=True, exist_ok=True)
    trajectory_path = agent_log_dir / "trajectory.log"

    registry = ToolRegistry()
    register_all_tools(registry, data_root=data_root)
    model_env = load_model_env("AGENT_EVAL")
    model_id = model or model_env.model or DEFAULT_MODEL
    agent = MiniAgent(
        client=LLMClient(
            model_id=model_id,
            api_key=model_env.api_key,
            base_url=model_env.base_url,
        ),
        registry=registry,
        trajectory=TrajectoryLogger(trajectory_path),
        max_steps=max_steps,
        temperature=temperature,
        parallel_tool_calls=parallel_tool_calls,
        reasoning_effort=reasoning_effort,
    )

    print(f"  Model:               {model_id}")
    print(f"  Temperature:         {temperature if temperature is not None else 'api-default'}")
    print(f"  Parallel tool calls: {parallel_tool_calls}")
    print(f"  Reasoning effort:    {reasoning_effort or 'disabled'}")
    print(f"  Tools:               {len(registry.tool_names)}")
    print(f"  Max steps:           {max_steps}")
    print(f"  Trajectory:          {trajectory_path}")

    try:
        result = agent.run(instruction)
        (agent_log_dir / "stdout.txt").write_text(result)
        print(f"  Agent completed. Result: {result[:200]}...")
        return True
    except Exception as e:
        print(f"  Agent error: {e}")
        (agent_log_dir / "stderr.txt").write_text(str(e))
        return False


def run_evaluation(task_dir: Path, job_dir: Path) -> bool:
    """Run pytest evaluation. Writes verifier logs to job_dir."""
    print("[4/4] Running evaluation...")
    test_file = task_dir / "tests" / "test_outputs.py"
    if not test_file.exists():
        print(f"  SKIP: No test file at {test_file}")
        return True

    verifier_log_dir = job_dir / "logs" / "verifier"
    verifier_log_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_eval.py"),
            str(task_dir),
            "--job-dir", str(job_dir),
        ],
        capture_output=True, text=True,
    )
    (verifier_log_dir / "pytest_output.txt").write_text(result.stdout + "\n" + result.stderr)
    print(result.stdout)

    if result.returncode != 0:
        print(f"  Some tests failed (exit code {result.returncode})")
        return False
    print("  All tests passed!")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CSV-only oncology task runner")
    parser.add_argument(
        "task_folder",
        help="Path to task folder, e.g. tasks/oncology-v1/<case_id>",
    )
    parser.add_argument("--model", "-m",
                        help="Model ID (OpenRouter format)")
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--no-parallel-tools", action="store_true",
                        help="Disable parallel tool calls")
    parser.add_argument("--reasoning-effort", default=None,
                        choices=["low", "medium", "high"])
    parser.add_argument("--skip-agent", action="store_true",
                        help="Skip agent run; only invoke eval against existing job_dir")
    parser.add_argument("--skip-eval", action="store_true")
    parser.add_argument("--job-dir",
                        help="Explicit per-task job directory. If omitted, one is auto-created "
                             "under jobs/<batch>/<task>/.")
    parser.add_argument("--data-root", type=Path,
                        default=DEFAULT_DATA_ROOT,
                        help="Oncology dataset root containing cleaned/")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()

    args = parser.parse_args(argv)

    task_dir = Path(args.task_folder).resolve()
    if not task_dir.exists():
        task_dir = (REPO_ROOT / args.task_folder).resolve()
    if not task_dir.exists():
        print(f"ERROR: Task folder not found: {args.task_folder}")
        return 1

    try:
        cleaned_root = resolve_cleaned_data_root(args.data_root)
        case_id = validate_oncology_task_contract(task_dir, cleaned_root)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1

    from scripts.pipeline_env import load_model_env
    model_env = load_model_env("AGENT_EVAL")
    model_id = args.model or model_env.model or DEFAULT_MODEL

    # Resolve job_dir up front — all run artifacts go here.
    from scripts.job_manager import (
        create_job_dir, write_metadata, parse_pytest_results,
    )
    if args.job_dir:
        job_dir = Path(args.job_dir).resolve()
        job_dir.mkdir(parents=True, exist_ok=True)
    else:
        job_dir = create_job_dir(
            model=model_id, task_name=task_dir.name,
            reasoning_effort=args.reasoning_effort or "",
            temperature=str(args.temperature) if args.temperature is not None else "default",
        )

    print(f"Task:    {task_dir.name}")
    print(f"Case:    {case_id}")
    print(f"Job:     {job_dir}")
    print(f"CSV:     {cleaned_root}")
    print(f"Model:   {model_id}")
    print()

    task_cost = None
    success = True
    print("[1/4] Using read-only cleaned oncology CSV data")
    print()

    if not args.skip_agent:
        usage_before = get_openrouter_usage()
        if not run_agent(
            task_dir, job_dir, model_id, args.max_steps,
            temperature=args.temperature,
            parallel_tool_calls=not args.no_parallel_tools,
            reasoning_effort=args.reasoning_effort,
            data_root=cleaned_root,
        ):
            print("WARNING: Agent exited with error, continuing to eval...")
        usage_after = get_openrouter_usage()
        if usage_before is not None and usage_after is not None:
            task_cost = round(usage_after - usage_before, 6)
            print(f"  OpenRouter cost for this task: ${task_cost:.4f}")
    else:
        print("[3/4] Skipping agent (--skip-agent)")

    if not args.skip_eval:
        success = run_evaluation(task_dir, job_dir)
    else:
        print("[4/4] Skipping evaluation (--skip-eval)")

    pytest_file = job_dir / "logs" / "verifier" / "pytest_output.txt"
    test_results = parse_pytest_results(pytest_file.read_text()) if pytest_file.exists() else {}
    write_metadata(
        job_dir,
        model=model_id,
        task=task_dir.name,
        max_steps=args.max_steps,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
        data_root=str(cleaned_root),
        success=success,
        test_results=test_results,
        task_cost_usd=task_cost,
    )
    print(f"\nJob written: {job_dir}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
