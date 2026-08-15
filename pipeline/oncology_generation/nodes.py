from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.csv_event_store import CsvEventStore
from tools.csv_event_types import EventQuery, SUPPORTED_CATEGORIES

from .schemas import GenerationState, validate_state


def load_case(data_root: Path, case_id: str) -> dict[str, Any]:
    events: list[dict[str, str]] = []
    store = CsvEventStore(data_root)
    for category in SUPPORTED_CATEGORIES:
        events.extend(store.query(EventQuery(case_id, category=category, limit=10000)))
    return {"case_id": case_id, "raw_events": events}


def build_timeline(state: GenerationState) -> dict[str, Any]:
    events = sorted(state.get("raw_events", []), key=lambda e: (e.get("event_date", ""), e.get("encnt_no", ""), e.get("group_id", ""), e.get("_source_row", "")))
    groups: dict[str, list[dict[str, str]]] = {}
    for event in events:
        groups.setdefault(event.get("group_id", ""), []).append(event)
    return {"raw_events": events, "candidate_segments": list(groups.values())}


def parse_model_json(client, prompt: str) -> dict[str, Any]:
    response = client.chat([{"role": "user", "content": prompt}])
    content = response.content or ""
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model returned invalid JSON: {exc}") from exc


def select_anchor(state: GenerationState, client) -> dict[str, Any]:
    compact = json.dumps(state.get("candidate_segments", [])[:20], ensure_ascii=False)
    return {"selected_segment": parse_model_json(client, f"Select one real clinical event segment as task anchor. Return JSON with group_id, rationale, evidence_refs. Data: {compact}")}


def draft_task(state: GenerationState, client) -> dict[str, Any]:
    segment = json.dumps(state.get("selected_segment", {}), ensure_ascii=False)
    return {"task_draft": parse_model_json(client, f"Draft a clinical Agent task from this evidence. Do not reveal evaluator criteria or answers. Return JSON with title, instruction, deliverable. Evidence: {segment}")}


def draft_checkpoints(state: GenerationState, client) -> dict[str, Any]:
    context = json.dumps({"task": state.get("task_draft", {}), "events": state.get("raw_events", [])}, ensure_ascii=False)
    result = parse_model_json(client, f"Generate 3-6 retrieval/reasoning/documentation checkpoints. Each must cite raw event refs and tools. Return JSON {{\"checkpoints\": [...]}}. Context: {context}")
    return {"checkpoint_drafts": result.get("checkpoints", [])}


def validate_node(state: GenerationState, allowed_tools: set[str]) -> dict[str, Any]:
    errors = validate_state(state, allowed_tools)
    return {"validation_errors": errors, "review_status": "approved" if not errors else "needs_revision"}


def persist_state(state: GenerationState, output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
