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
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run evaluation for a single task")
    parser.add_argument("task_folder", help="Path to task folder")
    parser.add_argument(
        "--job-dir",
        help="Per-task job directory (provides workspace/ and logs/). "
             "If omitted, the test file falls back to the in-task layout.",
    )
    args = parser.parse_args()

    task_dir = Path(args.task_folder).resolve()
    test_path = task_dir / "tests" / "test_outputs.py"

    if not test_path.exists():
        print(f"No test file at {test_path}")
        sys.exit(0)

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
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
