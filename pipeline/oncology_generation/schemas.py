from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict


class GenerationState(TypedDict, total=False):
    case_id: str
    raw_events: list[dict[str, str]]
    event_groups: list[EventGroup]
    target_group_id: str
    target_events: list[dict[str, str]]
    task_draft: dict[str, Any]
    cleaned_path: Path
    validation_errors: list[str]
    review_status: str


@dataclass(frozen=True)
class EventGroup:
    group_id: str
    event_date: str
    first_source_row: int
    category: str
    events: list[dict[str, str]]


@dataclass(frozen=True)
class CleaningResult:
    cleaned_csv: Path
    target_group_id: str
    target_events: list[dict[str, str]]


def validate_state(state: GenerationState, allowed_tools: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    groups = state.get("event_groups", [])
    target_id = state.get("target_group_id", "")
    target_group = next((group for group in groups if group.group_id == target_id), None)
    if target_group is None:
        errors.append(f"target group does not exist: {target_id}")
    target_events = state.get("target_events", [])
    raw_keys = {_event_key(event) for event in state.get("raw_events", [])}
    untraceable = [_event_key(event) for event in target_events if _event_key(event) not in raw_keys]
    if untraceable:
        errors.append(f"target events cannot be traced to raw events: {untraceable}")
    if target_group is not None:
        group_keys = {_event_key(event) for event in target_group.events}
        target_keys = {_event_key(event) for event in target_events}
        missing = [_event_key(event) for event in target_events if _event_key(event) not in group_keys]
        if missing:
            errors.append(f"target events cannot be traced to target group: {missing}")
        omitted = sorted(group_keys - target_keys)
        if omitted:
            errors.append(f"target group rows are missing from target events: {omitted}")
        if not any(_is_diagnostic_event(event) for event in target_group.events):
            errors.append("target group has no diagnostic feature_name/value")

    cleaned_path = state.get("cleaned_path")
    if cleaned_path is None:
        errors.append("cleaned path is missing")
    else:
        path = Path(cleaned_path)
        if path.parent.name != "cleaned":
            errors.append("cleaned output path is outside cleaned directory")
        if not path.is_file():
            errors.append(f"cleaned file does not exist: {path}")
        else:
            import csv
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                cleaned_groups = {row.get("group_id", "") for row in csv.DictReader(stream)}
            later_groups = {group.group_id for group in groups if target_group is not None and group.first_source_row >= target_group.first_source_row}
            leaked = cleaned_groups & later_groups
            if leaked:
                errors.append(f"cleaned file contains target or following groups: {sorted(leaked)}")

    instruction = str(state.get("task_draft", {}).get("instruction", ""))
    source_events = target_group.events if target_group is not None else target_events
    target_values = {event.get("value", "") for event in source_events if event.get("value", "")}
    leaked_values = [value for value in target_values if value in instruction]
    if leaked_values:
        errors.append(f"task instruction contains target value: {leaked_values}")
    return errors


def _event_key(event: dict[str, str]) -> tuple[str, str, str, str]:
    return (event.get("_source_row", ""), event.get("category", ""), event.get("feature_name", ""), event.get("value", ""))


def _is_diagnostic_event(event: dict[str, str]) -> bool:
    return bool(event.get("feature_name", "").strip() and event.get("value", "").strip() and "诊断" in event.get("feature_name", ""))
