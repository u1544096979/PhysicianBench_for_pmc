from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

CheckpointKind = Literal["retrieval", "reasoning", "documentation"]


class GenerationState(TypedDict, total=False):
    case_id: str
    raw_events: list[dict[str, str]]
    candidate_segments: list[list[dict[str, str]]]
    selected_segment: dict[str, Any]
    task_draft: dict[str, Any]
    checkpoint_drafts: list[dict[str, Any]]
    validation_errors: list[str]
    review_status: str


@dataclass(frozen=True)
class EvidenceRef:
    row: int
    category: str
    subject: str
    feature_name: str
    value: str


@dataclass(frozen=True)
class CheckpointDraft:
    kind: CheckpointKind
    objective: str
    tool_names: list[str]
    evidence_refs: list[EvidenceRef]
    verification: str
    pass_criteria: str


def validate_state(state: GenerationState, allowed_tools: set[str]) -> list[str]:
    errors: list[str] = []
    events = state.get("raw_events", [])
    event_keys = {(event.get("_source_row", ""), event.get("category", ""), event.get("feature_name", ""), event.get("value", "")) for event in events}
    for index, checkpoint in enumerate(state.get("checkpoint_drafts", [])):
        if checkpoint.get("kind") not in {"retrieval", "reasoning", "documentation"}:
            errors.append(f"checkpoint[{index}] has unsupported kind")
        if not checkpoint.get("objective") or not checkpoint.get("pass_criteria"):
            errors.append(f"checkpoint[{index}] is missing objective or pass criteria")
        for tool_name in checkpoint.get("tool_names", []):
            if tool_name not in allowed_tools:
                errors.append(f"checkpoint[{index}] uses unknown tool: {tool_name}")
        for ref in checkpoint.get("evidence_refs", []):
            key = (str(ref.get("row", "")), ref.get("category", ""), ref.get("feature_name", ""), ref.get("value", ""))
            if key not in event_keys:
                errors.append(f"checkpoint[{index}] references missing evidence: {key}")
    instruction = str(state.get("task_draft", {}).get("instruction", ""))
    if "ground_truth" in instruction.lower() or "pass_criteria" in instruction.lower():
        errors.append("task instruction leaks evaluator fields")
    return errors
