"""OncoBench 轨迹浏览 纯函数扫描层：目录 → 结构化数据模型。

只读 `tasks/oncology-v2/<case_id>/...` 产物，不依赖 FastAPI，可纯函数单测。
每次调用现读文件、无缓存（手动刷新语义由此保证）。
spec: 2026-08-21-trajectory-viewer-design.md §4.2
"""
from __future__ import annotations

import csv
import json
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path

import markdown as _md


# ---------------------------------------------------------------- 数据模型
@dataclass
class TaskInfo:
    case_id: str
    task_type: str = ""
    task_label: str = ""
    target_date: str = ""
    run_count: int = 0
    best_score: float | None = None
    recent_passed: int | None = None
    recent_total: int | None = None


@dataclass
class RunSummary:
    run_id: str
    agent_model: str | None = None
    tool_calls: int | None = None
    pass_count: int | None = None
    total_count: int | None = None
    score: float | None = None
    status: str = "complete"
    duration_seconds: float | None = None
    start_time: str | None = None


@dataclass
class TaskDetail:
    case_id: str
    task_type: str = ""
    task_label: str = ""
    target_date: str = ""
    instruction_md: str = ""
    instruction_html: str = ""
    checkpoints: list[dict] = field(default_factory=list)
    has_ground_truth: bool = False
    has_cleaned_csv: bool = False
    runs: list[RunSummary] = field(default_factory=list)


@dataclass
class RunDetail:
    case_id: str
    run_id: str
    has_scorecard: bool = False
    scorecard: dict | None = None
    checkpoints: list[dict] = field(default_factory=list)
    checkpoint_summary: dict | None = None
    agent_model: str | None = None
    tool_calls: int | None = None
    status: str = "incomplete"
    duration_seconds: float | None = None
    start_time: str | None = None
    events: list[dict] = field(default_factory=list)
    failed_lines: int = 0
    report_md: str = ""
    report_html: str = ""
    ground_truth: dict | None = None
    cleaned_csv_html: str = ""


# ---------------------------------------------------------------- 内部工具
def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _render_md(text: str) -> str:
    # 每次调用新建 Markdown 实例：模块级共享实例非线程安全，
    # 同步 FastAPI 端点跑在线程池里，可能并发调用。
    return _md.markdown(text, extensions=["fenced_code"]) if text else ""


def _csv_to_table(path: Path) -> str:
    if not path.exists():
        return ""
    with open(path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return "<p>（空文件）</p>"
    thead = "<tr>" + "".join(f"<th>{escape(h)}</th>" for h in rows[0]) + "</tr>"
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>"
        for row in rows[1:]
    )
    return (f"<div class='table-wrap'><table><thead>{thead}</thead>"
            f"<tbody>{body}</tbody></table></div>")


def _parse_trajectory(path: Path) -> tuple[list[dict], int]:
    """逐行 json.loads；坏行跳过并计数。"""
    events: list[dict] = []
    failed = 0
    for line in _read_text(path).splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            failed += 1
            continue
        if not isinstance(obj, dict):
            # 合法 JSON 但不是对象（null/list/str 等）：跳过，
            # 保证 events 里每个元素都支持 .get()。
            continue
        events.append(obj)
    return events, failed


def _first_timestamp(events: list[dict]) -> str | None:
    for ev in events:
        ts = ev.get("timestamp")
        if ts:
            return ts
    return None


def _duration_seconds(first: str | None, last: str | None) -> float | None:
    if not first or not last:
        return None
    try:
        return (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds()
    except (ValueError, TypeError):
        return None


def _read_report(run_dir: Path) -> tuple[str, str]:
    """取 output/ 下第一个 .md 作为交付报告：返回(原文, HTML)。"""
    out_dir = run_dir / "output"
    md_files = sorted(out_dir.glob("*.md")) if out_dir.is_dir() else []
    if not md_files:
        return "", ""
    text = md_files[0].read_text(encoding="utf-8")
    return text, _render_md(text)


# ---------------------------------------------------------------- run
def load_run(root: Path, case_id: str, run_id: str) -> RunDetail:
    """读单个 run：scorecard + trajectory 事件 + 报告 + 病例 ground_truth + CSV 表。"""
    case_dir = root / case_id
    run_dir = case_dir / "runs" / run_id
    sc = _read_json(run_dir / "scorecard.json")
    checkpoints: list[dict] = []
    checkpoint_summary = None
    if sc is not None:
        checkpoints = sc.get("checkpoints", []) or []
        checkpoint_summary = sc.get("checkpoint_summary")
    events, failed = _parse_trajectory(run_dir / "trajectory.json")
    first = _first_timestamp(events)
    last = events[-1].get("timestamp") if events else None
    duration = _duration_seconds(first, last)
    report_md, report_html = _read_report(run_dir)
    return RunDetail(
        case_id=case_id,
        run_id=run_id,
        has_scorecard=sc is not None,
        scorecard=sc,
        checkpoints=checkpoints,
        checkpoint_summary=checkpoint_summary,
        agent_model=sc.get("agent_model") if sc else None,
        tool_calls=sc.get("tool_calls") if sc else None,
        status="complete" if sc is not None else "incomplete",
        duration_seconds=duration,
        start_time=first,
        events=events,
        failed_lines=failed,
        report_md=report_md,
        report_html=report_html,
        ground_truth=_read_json(case_dir / "ground_truth.json"),
        cleaned_csv_html=_csv_to_table(case_dir / "cleaned_trajectory.csv"),
    )


# ---------------------------------------------------------------- task
def _list_runs(runs_dir: Path) -> list[RunSummary]:
    if not runs_dir.is_dir():
        return []
    out = []
    for d in sorted(runs_dir.glob("*")):
        if not d.is_dir():
            continue
        sc = _read_json(d / "scorecard.json")
        s = RunSummary(run_id=d.name)
        if sc is not None:
            s.agent_model = sc.get("agent_model")
            s.tool_calls = sc.get("tool_calls")
            cs = sc.get("checkpoint_summary") or {}
            s.pass_count = cs.get("pass")
            s.total_count = cs.get("total")
            s.score = cs.get("score")
        else:
            s.status = "incomplete"
        events, _ = _parse_trajectory(d / "trajectory.json")
        first = _first_timestamp(events)
        last = events[-1].get("timestamp") if events else None
        s.start_time = first
        s.duration_seconds = _duration_seconds(first, last)
        out.append(s)
    return out


def load_task(root: Path, case_id: str) -> TaskDetail:
    case_dir = root / case_id
    meta = tomllib.loads((case_dir / "task.toml").read_text(encoding="utf-8"))
    instruction_raw = _read_text(case_dir / "instruction.md")
    checkpoints = (_read_json(case_dir / "checkpoints.json") or {}).get("checkpoints", []) or []
    return TaskDetail(
        case_id=case_id,
        task_type=meta.get("task_type", ""),
        task_label=meta.get("task_label", ""),
        target_date=meta.get("target_date", ""),
        instruction_md=instruction_raw,
        instruction_html=_render_md(instruction_raw),
        checkpoints=checkpoints,
        has_ground_truth=(case_dir / "ground_truth.json").exists(),
        has_cleaned_csv=(case_dir / "cleaned_trajectory.csv").exists(),
        runs=_list_runs(case_dir / "runs"),
    )


# ---------------------------------------------------------------- 顶层扫描
def _scan_task(case_dir: Path) -> TaskInfo | None:
    try:
        meta = tomllib.loads((case_dir / "task.toml").read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return None
    runs = _list_runs(case_dir / "runs")
    best = None
    recent_passed = recent_total = None
    if runs:
        for rs in runs:
            if rs.score is not None:
                best = rs.score if best is None else max(best, rs.score)
        recent_passed, recent_total = runs[-1].pass_count, runs[-1].total_count
    return TaskInfo(
        case_id=meta.get("case_id", case_dir.name),
        task_type=meta.get("task_type", ""),
        task_label=meta.get("task_label", ""),
        target_date=meta.get("target_date", ""),
        run_count=len(runs),
        best_score=best,
        recent_passed=recent_passed,
        recent_total=recent_total,
    )


def scan_tasks(root: Path) -> list[TaskInfo]:
    """遍历 `root/*/`，读 task.toml + 统计 runs，返回病例列表。"""
    out: list[TaskInfo] = []
    for case_dir in sorted(d for d in root.glob("*") if d.is_dir()):
        info = _scan_task(case_dir)
        if info is not None:
            out.append(info)
    return out
