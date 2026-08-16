from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.csv_event_store import CsvEventStore
from tools.csv_event_types import EventQuery, SUPPORTED_CATEGORIES

from .schemas import EventGroup, GenerationState, validate_state


def load_case(data_root: Path, case_id: str) -> dict[str, Any]:
    events: list[dict[str, str]] = []
    store = CsvEventStore(data_root)
    for category in SUPPORTED_CATEGORIES:
        events.extend(store.query(EventQuery(case_id, category=category, limit=10000)))
    return {"case_id": case_id, "raw_events": events}


def build_timeline(state: GenerationState) -> dict[str, Any]:
    events = sorted(state.get("raw_events", []), key=_source_row)
    return {"raw_events": events, "event_groups": build_event_groups(events)}


def _source_row(event: dict[str, str]) -> int:
    try:
        return int(event.get("_source_row", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError("event is missing a numeric _source_row") from exc


def build_event_groups(events: list[dict[str, str]]) -> list[EventGroup]:
    groups_by_id: dict[str, list[dict[str, str]]] = {}
    for event in sorted(events, key=_source_row):
        groups_by_id.setdefault(event.get("group_id", ""), []).append(event)

    groups = []
    for group_events in groups_by_id.values():
        first = group_events[0]
        groups.append(
            EventGroup(
                group_id=first.get("group_id", ""),
                event_date=first.get("event_date", ""),
                first_source_row=_source_row(first),
                category=first.get("category", ""),
                events=group_events,
            )
        )
    return sorted(groups, key=lambda group: group.first_source_row)


def parse_model_json(client, prompt: str) -> dict[str, Any]:
    response = client.chat([{"role": "user", "content": prompt}])
    content = response.content or ""
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model returned invalid JSON: {exc}") from exc


def select_target_group(state: GenerationState, client) -> dict[str, Any]:
    context = json.dumps({"case_id": state.get("case_id"), "events": state.get("raw_events", [])}, ensure_ascii=False)
    prompt = (
        "从完整病例中选择一个真实诊断性事件组。目标可以来自任意 category，但必须有明确的 feature_name/value 诊断信息。"
        "不得泄漏目标组的 value；instruction 只能描述任务，不得写出答案。"
        "只返回 JSON：target_group_id、selection_rationale、role、instruction、deliverable。"
        f"完整病例：{context}"
    )
    result = parse_model_json(client, prompt)
    target_id = str(result.get("target_group_id", ""))
    target_group = next((group for group in state.get("event_groups", []) if group.group_id == target_id), None)
    if target_group is None:
        raise ValueError(f"model selected unknown target group: {target_id}")
    draft = {key: result[key] for key in ("selection_rationale", "role", "instruction", "deliverable") if key in result}
    return {"target_group_id": target_id, "target_events": target_group.events, "task_draft": draft}


def materialize_cleaned_node(state: GenerationState, data_root: Path) -> dict[str, Any]:
    from .cleaning import materialize_cleaned_case

    result = materialize_cleaned_case(data_root / "raw" / "csv" / f"{state['case_id']}.csv", data_root / "cleaned" / f"{state['case_id']}.csv", state["target_group_id"])
    return {"target_events": result.target_events, "cleaned_path": result.cleaned_csv}


def validate_node(state: GenerationState) -> dict[str, Any]:
    errors = validate_state(state)
    return {"validation_errors": errors, "review_status": "approved" if not errors else "needs_revision"}


def persist_state(state: GenerationState, output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
