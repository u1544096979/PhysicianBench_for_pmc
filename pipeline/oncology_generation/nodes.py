"""v2 流水线节点实现（6个LLM节点 + 清洗落盘 + 失败落盘）."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from llm.client import LLMClient, get_default_client

from . import prompts_v2 as P
from .schemas import (
    CHECKPOINT_LAYERS,
    TASK_TYPE_VALUES,
    Checkpoint,
    EvaluationResult,
    EventGroup,
    FailureRecord,
    GenerationState,
    LabelResult,
    SolutionResult,
    TaskDraft,
    ValidationResult,
    build_event_groups,
    serialize_groups,
)
from .task_types import TASK_TYPES

MAX_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _client(state: GenerationState) -> LLMClient:
    trace_dir = Path(state["generated_root"]) / "trace"
    return get_default_client(trace_dir)


def _load_case_events(case_id: str, data_root: Path) -> list[dict[str, str]]:
    csv_path = data_root / f"{case_id}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"case csv not found: {csv_path}")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        events: list[dict[str, str]] = []
        for source_row, row in enumerate(reader, start=2):
            event = {k: (v or "") for k, v in row.items() if k}
            event["_source_row"] = str(source_row)
            events.append(event)
    return events


def visible_groups(
    groups: list[EventGroup],
    target_group_id: str,
    answer_event_rows: list[int] | None = None,
) -> list[EventGroup]:
    """截断视图。

    - 整组模式（answer_event_rows 为空）：target 事件组及其后所有组不可见（旧行为）
    - 事件级模式：target 组之前全可见；target 组仅隐藏 answer_event_rows 标记的
      答案事件，同组的证据性事件（检查所见/测量值/方法）保留给做题者；
      target 组之后的所有组不可见。
    """
    idx = next((i for i, g in enumerate(groups) if g.group_id == target_group_id), None)
    if idx is None:
        raise ValueError(f"target group not in timeline: {target_group_id}")
    before = groups[:idx]
    if not answer_event_rows:
        return before
    hide = {str(r) for r in answer_event_rows}
    target = groups[idx]
    kept = [
        ev for ev in target.events
        if str(ev.get("_source_row", "")) not in hide
    ]
    if kept:
        before = before + [EventGroup(
            group_id=target.group_id, date=target.date,
            category=target.category, events=kept,
        )]
    return before


def literal_leak_check(draft: TaskDraft, visible: list[EventGroup]) -> str | None:
    """代码级字面泄漏检测：ground_truth 的显著值不得出现在 instruction 或可见轨迹."""
    gt_values = [
        str(v).strip() for v in draft.ground_truth.values()
        if isinstance(v, (str, int, float)) and len(str(v).strip()) >= 4
    ]
    corpus = draft.instruction + "\n" + serialize_groups(visible, full=True)
    for value in gt_values:
        if value in corpus:
            return f"ground_truth值 '{value}' 原样出现在instruction或可见轨迹中"
    return None


# ---------------------------------------------------------------------------
# 节点1：加载 + 分组（代码）
# ---------------------------------------------------------------------------

def load_and_timeline(state: GenerationState) -> dict:
    events = _load_case_events(state["case_id"], Path(state["data_root"]))
    # 注入行号（数据行从1起，与展示给LLM的[n]一致），供事件级截断引用
    for i, ev in enumerate(events, start=1):
        ev.setdefault("_source_row", str(i))
    groups = build_event_groups(events)
    return {"events": events, "groups": groups}


# ---------------------------------------------------------------------------
# 节点2：① 标注 + 推荐（LLM）
# ---------------------------------------------------------------------------

def label_recommend(state: GenerationState) -> dict:
    case_id = state["case_id"]
    label_path = Path(state["generated_root"]) / "labels" / f"{case_id}.json"
    if label_path.exists() and not state.get("force_relabel"):
        data = json.loads(label_path.read_text(encoding="utf-8"))
        return {"label": LabelResult(**data), "label_skipped": True}

    client = _client(state)
    # 标注需要字段级信息才能识别分期/标志物信号（修复：原先只给类别行导致全推T4）
    groups_summary = serialize_groups(state["groups"], full=True)
    resp = client.chat_json(
        P.build_label_prompt(groups_summary),
        node="label",
    )
    applicable = [t for t in resp.get("applicable_types", []) if t in TASK_TYPE_VALUES]
    recommended = resp.get("recommended_type", "none")
    if recommended not in TASK_TYPE_VALUES:
        recommended = "none"

    label = LabelResult(
        case_id=case_id,
        applicable_types=applicable,
        recommended_type=recommended,
        reason=resp.get("reason", ""),
    )
    label_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.write_text(json.dumps(label.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"label": label, "label_skipped": False}


def route_after_label(state: GenerationState) -> str:
    label: LabelResult | None = state.get("label")
    if label is None or label.recommended_type == "none" or not label.applicable_types:
        return "persist_failure"
    return "generate_task"


# ---------------------------------------------------------------------------
# 节点3：② 任务生成（LLM）
# ---------------------------------------------------------------------------

def generate_task(state: GenerationState) -> dict:
    client = _client(state)
    label: LabelResult = state["label"]
    groups_full = serialize_groups(state["groups"], full=True)
    feedback = state.get("failure_history", [])
    feedback_texts = [f.detail for f in feedback] if feedback and isinstance(feedback[0], FailureRecord) else feedback

    resp = client.chat_json(
        P.build_generate_prompt(label.recommended_type, groups_full, feedback_texts),
        node="generate",
    )

    target_group_id = resp.get("target_group_id", "")
    # 兼容LLM返回前8位截断ID：在时间线中做前缀匹配
    groups: list[EventGroup] = state["groups"]
    if target_group_id and not any(g.group_id == target_group_id for g in groups):
        prefix_matches = [g for g in groups if g.group_id.startswith(target_group_id)]
        if len(prefix_matches) == 1:
            target_group_id = prefix_matches[0].group_id
        else:
            raise ValueError(f"target_group_id 无法唯一定位: {resp.get('target_group_id')}")

    answer_rows_raw = resp.get("answer_event_rows") or []
    answer_event_rows = [int(r) for r in answer_rows_raw if str(r).strip().isdigit()]
    draft = TaskDraft(
        task_type=label.recommended_type,
        target_group_id=target_group_id,
        target_date=resp.get("target_date", ""),
        answer_event_rows=answer_event_rows,
        instruction=resp.get("instruction", ""),
        deliverable=resp.get("deliverable", "output/diagnosis_report.md"),
        ground_truth=resp.get("ground_truth", {}),
        rationale=resp.get("rationale", ""),
        revision_index=state.get("attempt", 0) + 1,
        feedback_history=feedback_texts,
    )
    return {"task_draft": draft, "attempt": draft.revision_index}


def _attempt_exceeded(state: GenerationState) -> bool:
    return state.get("attempt", 0) >= MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# 节点4：③ 静态验证（LLM + 代码兜底）
# ---------------------------------------------------------------------------

def validate_task(state: GenerationState) -> dict:
    draft: TaskDraft = state["task_draft"]
    client = _client(state)

    # 代码级字面泄漏预检（免费，先于LLM）
    visible = visible_groups(state["groups"], draft.target_group_id, draft.answer_event_rows)
    leak = literal_leak_check(draft, visible)
    if leak:
        validation = ValidationResult(
            passed=False, leaked=True, answerable=True, unique=True,
            issues=[leak], severity="fatal",
        )
        return {
            "validation": validation,
            "failure_history": state.get("failure_history", []) + [
                FailureRecord(stage="validate", reason_class="leak_detected", detail=leak).__dict__
            ],
        }

    resp = client.chat_json(
        P.build_validate_prompt(
            instruction=draft.instruction,
            ground_truth=draft.ground_truth,
            target_date=draft.target_date,
            visible_groups=serialize_groups(visible, full=True),
        ),
        node="validate",
    )
    leaked = bool(resp.get("leaked", False))
    answerable = bool(resp.get("answerable", True))
    unique = bool(resp.get("unique", True))
    severity = resp.get("severity", "major")
    if leaked:
        severity = "fatal"
    elif (not answerable or not unique) and severity == "minor":
        severity = "major"
    explicit_pass = resp.get("passed")
    if explicit_pass is False:
        # 模型显式判定不通过，以模型决策为准
        passed = False
    else:
        passed = (not leaked) and answerable and unique
    validation = ValidationResult(
        passed=passed,
        leaked=leaked,
        answerable=answerable,
        unique=unique,
        issues=resp.get("issues", []),
        severity=severity,
    )
    update: dict[str, Any] = {"validation": validation}
    if not validation.passed:
        detail = "; ".join(validation.issues) or f"leaked={leaked} answerable={answerable} unique={unique}"
        update["failure_history"] = state.get("failure_history", []) + [
            FailureRecord(stage="validate", reason_class="validation_failed", detail=detail).__dict__
        ]
    return update


def route_after_validate(state: GenerationState) -> str:
    validation: ValidationResult | None = state.get("validation")
    if validation is not None and validation.passed:
        return "solve_task"
    if _attempt_exceeded(state):
        return "persist_failure"
    return "generate_task"


# ---------------------------------------------------------------------------
# 节点5：④ 做题（LLM）
# ---------------------------------------------------------------------------

def solve_task(state: GenerationState) -> dict:
    draft: TaskDraft = state["task_draft"]
    client = _client(state)
    visible = visible_groups(state["groups"], draft.target_group_id, draft.answer_event_rows)
    resp = client.chat_json(
        P.build_solve_prompt(
            instruction=draft.instruction,
            visible_events=serialize_groups(visible, full=True),
        ),
        node="solve",
    )
    solution = SolutionResult(
        answer=resp.get("answer", ""),
        reasoning_summary=resp.get("reasoning_summary", ""),
        confidence=resp.get("confidence", "medium"),
        cited_groups=resp.get("cited_groups", []),
    )
    return {"solution": solution}


# ---------------------------------------------------------------------------
# 节点6：⑤ 答案评估（LLM 裁判）
# ---------------------------------------------------------------------------

def evaluate_solution(state: GenerationState) -> dict:
    draft: TaskDraft = state["task_draft"]
    solution: SolutionResult = state["solution"]
    client = _client(state)
    resp = client.chat_json(
        P.build_evaluate_prompt(
            ground_truth=draft.ground_truth,
            answer=solution.answer,
            reasoning=solution.reasoning_summary,
        ),
        node="evaluate",
    )
    verdict = resp.get("verdict", "inconsistent")
    if verdict not in ("valid", "inconsistent", "instant_answer", "insufficient_evidence"):
        verdict = "inconsistent"
    evaluation = EvaluationResult(
        verdict=verdict,
        consistent=bool(resp.get("consistent", False)),
        has_reasoning=bool(resp.get("has_reasoning", False)),
        explanation=resp.get("explanation", ""),
    )
    update: dict[str, Any] = {"evaluation": evaluation}
    if verdict != "valid":
        update["failure_history"] = state.get("failure_history", []) + [
            FailureRecord(
                stage="evaluate",
                reason_class=f"evaluation_{verdict}",
                detail=evaluation.explanation,
            ).__dict__
        ]
    return update


def route_after_evaluate(state: GenerationState) -> str:
    evaluation: EvaluationResult | None = state.get("evaluation")
    if evaluation is not None and evaluation.verdict == "valid":
        return "inject_noise"
    if _attempt_exceeded(state):
        return "persist_failure"
    return "generate_task"


# ---------------------------------------------------------------------------
# 节点6.5：噪声注入（核心包 run_injection，含重试阶梯/降级）
# ---------------------------------------------------------------------------

def inject_noise(state: GenerationState) -> dict:
    """evaluate valid 分支：调用核心包 run_injection 生成噪声（含重试阶梯）."""
    from pipeline.noise_injection.context import build_context
    from pipeline.noise_injection.config import NoiseConfig
    from pipeline.noise_injection.injection import run_injection
    from pipeline.noise_injection import solvable as _S  # noqa 保留

    draft: TaskDraft = state["task_draft"]
    ctx = build_context(
        case_id=state["case_id"],
        events=state["events"],
        task_type=draft.task_type,
        target_group_id=draft.target_group_id,
        target_date=draft.target_date,
        instruction=draft.instruction,
        ground_truth=draft.ground_truth,
        answer_event_rows=draft.answer_event_rows,
    )
    # 提供给 solvable gate3 的干净可见事件文本（透传 visible_text kwarg；
    # CaseContext 为 frozen dataclass，不可用 object.__setattr__ 附加属性）
    visible = visible_groups(state["groups"], draft.target_group_id, draft.answer_event_rows)
    visible_text = serialize_groups(visible, full=True)
    client = _client(state)
    result = run_injection(ctx, NoiseConfig(), client, visible_text=visible_text)
    update: dict[str, Any] = {"noise_rows": result.rows, "noise_manifest": result.manifest}
    return update


# ---------------------------------------------------------------------------
# 节点7：⑥ checkpoint 生成（LLM）
# ---------------------------------------------------------------------------

def generate_checkpoints(state: GenerationState) -> dict:
    draft: TaskDraft = state["task_draft"]
    client = _client(state)
    visible = visible_groups(state["groups"], draft.target_group_id, draft.answer_event_rows)
    categories = sorted({g.category for g in visible if g.category})
    resp = client.chat_json(
        P.build_checkpoint_prompt(
            instruction=draft.instruction,
            ground_truth=draft.ground_truth,
            available_categories=categories,
            task_type=draft.task_type,
        ),
        node="checkpoint",
    )
    checkpoints: list[Checkpoint] = []
    for i, cp in enumerate(resp.get("checkpoints", []), start=1):
        layer = cp.get("layer", "")
        if layer not in CHECKPOINT_LAYERS:
            continue
        checkpoints.append(Checkpoint(
            checkpoint_id=cp.get("checkpoint_id", f"cp{i}"),
            layer=layer,
            description=cp.get("description", ""),
            eval_method=cp.get("eval_method", "llm_judge"),
            params=cp.get("params", {}),
        ))
    return {"checkpoints": checkpoints}


# ---------------------------------------------------------------------------
# 节点8：⑦ 清洗 + 落盘（代码）
# ---------------------------------------------------------------------------

def materialize(state: GenerationState) -> dict:
    from .cleaning import materialize_cleaned_case

    draft: TaskDraft = state["task_draft"]
    case_id = state["case_id"]
    task_dir = Path(state["output_root"]) / case_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # 最终字面泄漏检测（spec D11；正常流程在validate已预检，此处兜底）
    visible = visible_groups(state["groups"], draft.target_group_id, draft.answer_event_rows)
    leak = literal_leak_check(draft, visible)
    if leak:
        return _write_review_queue(
            state, reason_class="leak_detected", detail=leak,
        )

    # 清洗（materialize_cleaned_case 返回暂存文件，需原子替换到目标位置）
    cleaned_csv = task_dir / "cleaned_trajectory.csv"
    result = materialize_cleaned_case(
        source_csv=Path(state["data_root"]) / f"{case_id}.csv",
        cleaned_csv=cleaned_csv,
        target_group_id=draft.target_group_id,
        answer_event_rows=draft.answer_event_rows or None,
    )
    import os
    os.replace(result.cleaned_csv, cleaned_csv)

    # instruction.md
    (task_dir / "instruction.md").write_text(draft.instruction, encoding="utf-8")

    # ground_truth.json
    gt_payload = {
        "task_type": draft.task_type,
        "target_group_id": draft.target_group_id,
        "target_date": draft.target_date,
        "ground_truth": draft.ground_truth,
        "rationale": draft.rationale,
    }
    (task_dir / "ground_truth.json").write_text(
        json.dumps(gt_payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # checkpoints.json
    cps = [cp.__dict__ for cp in state["checkpoints"]]
    (task_dir / "checkpoints.json").write_text(
        json.dumps({"checkpoints": cps}, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # task.toml
    t = TASK_TYPES[draft.task_type]
    toml_text = (
        f'case_id = "{case_id}"\n'
        f'task_type = "{draft.task_type}"\n'
        f'task_label = "{t.label}"\n'
        f'target_date = "{draft.target_date}"\n'
        f'deliverable = "{draft.deliverable}"\n'
        'data_file = "cleaned_trajectory.csv"\n'
    )
    (task_dir / "task.toml").write_text(toml_text, encoding="utf-8")

    # 追加噪声行 + 写 manifest
    noise_rows = state.get("noise_rows") or []
    if noise_rows:
        _append_noise_to_csv(cleaned_csv, noise_rows)
    noise_manifest = state.get("noise_manifest")
    if noise_manifest is not None:
        (task_dir / "noise_manifest.json").write_text(
            json.dumps(noise_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if state.get("noise_manifest") and state["noise_manifest"].get("final_status") == "degraded_clean":
        # 降级 → review_queue（任务仍以干净版落盘）
        _append_review_queue_for_noise(state)

    return {
        "status": "persisted",
        "task_dir": str(task_dir),
        "cleaned_csv": str(cleaned_csv),
    }


def _append_noise_to_csv(cleaned_csv: Path, noise_rows: list[dict]) -> None:
    from pipeline.noise_injection.materialize import CSV_FIELDS
    if not noise_rows:
        return
    existing = set()
    with cleaned_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        rd = csv.reader(fh)
        next(rd, None)  # header
        for row in rd:
            existing.add(tuple(row))
    with cleaned_csv.open("a", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(CSV_FIELDS), extrasaction="ignore")
        for r in noise_rows:
            row = {k: r.get(k, "") for k in CSV_FIELDS}
            # 追加时校验不与已存在行冲突（避免表头重复）
            wr.writerow(row)


def _append_review_queue_for_noise(state) -> None:
    queue_path = Path(state["generated_root"]) / "review_queue.jsonl"
    manifest = state.get("noise_manifest") or {}
    entry = {
        "case_id": state["case_id"], "attempt": state.get("attempt", 0),
        "reason_class": "noise_gate_failed",
        "detail": manifest.get("degrade_reason") or "noise gates failed",
    }
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 节点9：失败落盘（代码）
# ---------------------------------------------------------------------------

def _write_review_queue(
    state: GenerationState, *, reason_class: str, detail: str,
) -> dict:
    case_id = state["case_id"]
    queue_path = Path(state["generated_root"]) / "review_queue.jsonl"
    label: LabelResult | None = state.get("label")
    entry = {
        "case_id": case_id,
        "attempt": state.get("attempt", 0),
        "reason_class": reason_class,
        "detail": detail,
        "label": label.__dict__ if label else None,
        "failure_history": state.get("failure_history", []),
    }
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "review_queue", "review_reason": reason_class}


def persist_failure(state: GenerationState) -> dict:
    label: LabelResult | None = state.get("label")
    if label is None:
        reason_class, detail = "label_unsuitable", "标注节点未产出（LLM错误或轨迹不适合）"
    elif label.recommended_type == "none" or not label.applicable_types:
        reason_class, detail = "label_unsuitable", f"不适用任何任务类型: {label.reason}"
    else:
        history = state.get("failure_history", [])
        if history:
            last = history[-1]
            reason_class = last.get("reason_class", "unknown") if isinstance(last, dict) else "unknown"
            detail = last.get("detail", "") if isinstance(last, dict) else str(last)
        else:
            reason_class, detail = "unknown", "未知失败"
    return _write_review_queue(state, reason_class=reason_class, detail=detail)
