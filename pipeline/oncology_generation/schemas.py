"""v2 流水线数据结构（破坏性重写，替代旧版 schemas）."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypedDict

TaskTypeName = Literal["T1_staging", "T2_response", "T3_biomarker", "T4_diagnosis"]
TASK_TYPE_VALUES: tuple[str, ...] = ("T1_staging", "T2_response", "T3_biomarker", "T4_diagnosis")

# checkpoint 四层
CheckpointLayer = Literal["data_retrieval", "clinical_reasoning", "outcome_check", "documentation"]
CHECKPOINT_LAYERS: tuple[str, ...] = (
    "data_retrieval",
    "clinical_reasoning",
    "outcome_check",
    "documentation",
)

Severity = Literal["fatal", "major", "minor"]
EvaluationVerdict = Literal["valid", "inconsistent", "instant_answer", "insufficient_evidence"]


# ---------------------------------------------------------------------------
# 事件与事件组
# ---------------------------------------------------------------------------

@dataclass
class EventGroup:
    group_id: str
    date: str
    category: str
    events: list[dict[str, str]] = field(default_factory=list)

    def summary_line(self) -> str:
        return f"[{self.group_id[:8]}] {self.date or '日期缺失'} {self.category}"

    def full_text(self) -> str:
        lines = [self.summary_line()]
        for ev in self.events:
            feature = ev.get("feature_name", "")
            value = ev.get("value", "")
            extra = ev.get("extra_value", "")
            detail = f"{feature}: {value}" if feature or value else ""
            if extra:
                detail = f"{detail} ({extra})" if detail else str(extra)
            if detail:
                lines.append(f"  - {detail}")
        return "\n".join(lines)


def build_event_groups(events: list[dict[str, str]]) -> list[EventGroup]:
    """按 group_id 分组，保留首次出现顺序；组属性取组内首个非空值."""
    groups: list[EventGroup] = []
    index: dict[str, EventGroup] = {}
    for ev in events:
        gid = ev.get("group_id", "") or f"_nogroup_{len(groups)}"
        group = index.get(gid)
        if group is None:
            group = EventGroup(
                group_id=gid,
                date=ev.get("event_date", ""),
                category=ev.get("category", ""),
            )
            index[gid] = group
            groups.append(group)
        group.events.append(ev)
        if not group.date and ev.get("event_date"):
            group.date = ev["event_date"]
        if not group.category and ev.get("category"):
            group.category = ev["category"]
    return groups


def serialize_groups(groups: list[EventGroup], *, full: bool) -> str:
    blocks = [g.full_text() if full else g.summary_line() for g in groups]
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# ① 标注推荐
# ---------------------------------------------------------------------------

@dataclass
class LabelResult:
    case_id: str
    applicable_types: list[str]
    recommended_type: str
    reason: str
    review: str = ""  # ③的review_argument，可选


# ---------------------------------------------------------------------------
# ② 任务生成
# ---------------------------------------------------------------------------

@dataclass
class TaskDraft:
    task_type: str
    target_group_id: str
    target_date: str
    instruction: str
    deliverable: str
    ground_truth: dict[str, Any]
    rationale: str = ""
    revision_index: int = 0
    feedback_history: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ③ 静态验证
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    passed: bool
    leaked: bool
    answerable: bool
    unique: bool
    issues: list[str] = field(default_factory=list)
    severity: str = "major"  # fatal / major / minor


# ---------------------------------------------------------------------------
# ④ 做题
# ---------------------------------------------------------------------------

@dataclass
class SolutionResult:
    answer: str
    reasoning_summary: str
    confidence: str = "medium"
    cited_groups: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ⑤ 答案评估
# ---------------------------------------------------------------------------

@dataclass
class EvaluationResult:
    verdict: str  # valid / inconsistent / instant_answer / insufficient_evidence
    consistent: bool
    has_reasoning: bool
    explanation: str = ""


# ---------------------------------------------------------------------------
# ⑥ checkpoint
# ---------------------------------------------------------------------------

@dataclass
class Checkpoint:
    checkpoint_id: str
    layer: str
    description: str
    eval_method: str  # category_query / field_match / llm_judge
    params: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 失败记录 / 清洗结果
# ---------------------------------------------------------------------------

@dataclass
class FailureRecord:
    stage: str
    reason_class: str
    detail: str


@dataclass
class CleaningResult:
    cleaned_csv: Path
    target_group_id: str
    target_events: list[dict[str, str]]


# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------

class GenerationState(TypedDict, total=False):
    """流水线状态容器（TypedDict 供 LangGraph 识别 channel）."""
    case_id: str
    data_root: str
    output_root: str
    generated_root: str
    force_relabel: bool
    events: list[dict[str, str]]
    groups: list[EventGroup]
    label: LabelResult | None
    label_skipped: bool
    task_draft: TaskDraft | None
    validation: ValidationResult | None
    solution: SolutionResult | None
    evaluation: EvaluationResult | None
    checkpoints: list[Checkpoint]
    attempt: int
    failure_history: list[dict[str, Any]]
    status: str
    review_reason: str
    cleaned_csv: str
    task_dir: str


def new_state(
    *,
    case_id: str,
    data_root: Path,
    output_root: Path,
    generated_root: Path,
    force_relabel: bool = False,
) -> GenerationState:
    return GenerationState(
        case_id=case_id,
        data_root=str(data_root),
        output_root=str(output_root),
        generated_root=str(generated_root),
        force_relabel=force_relabel,
        # runtime
        events=[],
        groups=[],
        label=None,
        label_skipped=False,
        task_draft=None,
        validation=None,
        solution=None,
        evaluation=None,
        checkpoints=[],
        attempt=0,
        failure_history=[],
        status="running",  # running / persisted / review_queue
        review_reason="",
        cleaned_csv="",
        task_dir="",
    )
