"""OncoBench 评测运行器：任务包 → 考生agent解题 → checkpoint判分 → scorecard.

spec: 2026-08-20-oncobench-eval-loop-v1.md §5/§6
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx
from openai import OpenAI

from agent.llm_client import LLMClient as AgentLLMClient
from agent.mini_agent import MiniAgent
from agent.oncology_prompts import ONCOLOGY_SYSTEM_PROMPT
from agent.tool_registry import ToolRegistry
from agent.trajectory import TrajectoryLogger
from eval.checkpoint_executor import execute_checkpoints
from llm.client import LLMClient, get_default_client
from tools.oncology_tools import OncologyToolkit


def _agent_client_from_env() -> AgentLLMClient:
    """按 AGENT_LLM_* 构造考生客户端；未配置时回退 GEN_LLM_*；再回退默认."""
    base = os.environ.get("AGENT_LLM_BASE_URL") or os.environ.get("GEN_LLM_BASE_URL", "")
    key = os.environ.get("AGENT_LLM_API_KEY") or os.environ.get("GEN_LLM_API_KEY", "")
    model = os.environ.get("AGENT_LLM_MODEL") or os.environ.get("GEN_LLM_MODEL", "gpt-4o")
    if base and key:
        http_client = httpx.Client(verify=False, timeout=600)
        inner = OpenAI(base_url=base, api_key=key, http_client=http_client, max_retries=3)
        client = AgentLLMClient(model_id=model, api_key=key, base_url=base)
        client.client = inner
        # qwen3.8 must disable thinking (same lesson as generation side)
        client.extra_body = {"chat_template_kwargs": {"enable_thinking": False}}
        return client
    return AgentLLMClient(model_id=model)


def run_task(task_dir: Path, *, max_turns: int = 30, workdir: Path | None = None) -> dict:
    """跑一道题，返回scorecard dict并落盘."""
    task_dir = Path(task_dir)
    case_id = task_dir.name

    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    gt_data = json.loads((task_dir / "ground_truth.json").read_text(encoding="utf-8"))
    ground_truth = gt_data.get("ground_truth", gt_data)
    checkpoints = json.loads((task_dir / "checkpoints.json").read_text(encoding="utf-8"))["checkpoints"]

    # 工作目录（考生写报告的地方）
    workdir = workdir or (task_dir / "runs" / time.strftime("%Y%m%d-%H%M%S"))
    workdir.mkdir(parents=True, exist_ok=True)

    # 1. 工具集（绑定清洗后轨迹）
    kit = OncologyToolkit(
        case_id=case_id,
        cleaned_csv=task_dir / "cleaned_trajectory.csv",
        work_dir=workdir,
    )
    registry = ToolRegistry()
    fns = kit.get_tool_functions()
    for spec in kit.get_tool_specs():
        name = spec["function"]["name"]
        registry.register(name, fns[name], spec["function"])

    # 2. 考生agent
    agent_client = _agent_client_from_env()
    agent_model = agent_client.model_id
    traj_path = workdir / "trajectory.json"
    trajectory = TrajectoryLogger(traj_path)
    agent = MiniAgent(
        client=agent_client,
        registry=registry,
        trajectory=trajectory,
        system_prompt=ONCOLOGY_SYSTEM_PROMPT,
        max_steps=max_turns,
    )
    final = agent.run(instruction)

    # 3. 读报告
    report_path = workdir / "output" / "diagnosis_report.md"
    report_text = ""
    if report_path.exists():
        report_text = report_path.read_text(encoding="utf-8")
    else:
        # 兜底：从final消息或trajectory里找
        for alt in ["output/report.md", "output/diagnosis.md"]:
            p = workdir / alt
            if p.exists():
                report_text = p.read_text(encoding="utf-8")
                break
        if not report_text:
            report_text = f"【未产出报告】agent最终消息: {final}"

    # 4. 判分（裁判用GEN LLM；json mode + 禁思考）
    judge_client = get_default_client()
    cps_data = json.loads(json.dumps(checkpoints, ensure_ascii=False))
    score = execute_checkpoints(
        cps_data,
        report_text=report_text,
        ground_truth=ground_truth,
        call_log=kit.call_log,
        judge_client=judge_client,
    )

    # 5. scorecard落盘
    scorecard = {
        "case_id": case_id,
        "task_type": gt_data.get("task_type", ""),
        "agent_model": agent_model,
        "judge_model": judge_client.model if judge_client else "none",
        "final_message": str(final)[:500],
        "report_excerpt": report_text[:200],
        "tool_calls": len(kit.call_log),
        "checkpoint_summary": {k: score[k] for k in ("total", "pass", "fail", "error", "score")},
        "checkpoints": score["results"],
    }
    (workdir / "scorecard.json").write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return scorecard


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="跑一道OncoBench任务")
    parser.add_argument("--task-dir", required=True, type=Path)
    parser.add_argument("--max-turns", type=int, default=30)
    args = parser.parse_args()
    sc = run_task(args.task_dir, max_turns=args.max_turns)
    summary = sc["checkpoint_summary"]
    print(f"\n{'='*60}")
    print(f"得分卡: {summary['pass']}/{summary['total']} pass (score={summary['score']})")
    for r in sc["checkpoints"]:
        icon = {"pass": "✅", "fail": "❌", "error": "⚠️ "}.get(r["verdict"], "?")
        print(f"  {icon} {r['checkpoint_id']} [{r['layer']}] {r.get('comment','')[:70]}")
    print(f"工作目录: {args.task_dir}/runs/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
