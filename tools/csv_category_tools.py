"""Function-calling wrappers for the 14 oncology event categories."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .csv_event_store import CsvEventStore
from .csv_event_types import EventQuery, SUPPORTED_CATEGORIES

CATEGORY_TOOL_SPECS = (
    ("入院", "csv_search_admission_events", "admission"),
    ("病史", "csv_search_history_events", "history"),
    ("诊断", "csv_search_diagnosis_events", "diagnosis"),
    ("检验", "csv_search_lab_events", "laboratory"),
    ("影像", "csv_search_imaging_events", "imaging"),
    ("病理", "csv_search_pathology_events", "pathology"),
    ("手术", "csv_search_surgery_events", "surgery"),
    ("用药", "csv_search_medication_events", "medication"),
    ("病程", "csv_search_progress_events", "progress"),
    ("评估", "csv_search_assessment_events", "assessment"),
    ("不良反应", "csv_search_adverse_events", "adverse effects"),
    ("出院", "csv_search_discharge_events", "discharge"),
    ("会诊", "csv_search_consultation_events", "consultation"),
    ("其他", "csv_search_other_events", "other"),
)

assert tuple(item[0] for item in CATEGORY_TOOL_SPECS) == SUPPORTED_CATEGORIES


def make_category_tool(category: str, store: CsvEventStore) -> Callable:
    def search_events(
        case_id: str,
        subject: str | None = None,
        feature_name: str | None = None,
        event_date: str | None = None,
        group_id: str | None = None,
        limit: int = 100,
    ) -> dict:
        events = store.query(EventQuery(case_id, category, subject, feature_name, event_date, group_id, limit))
        return {"category": category, "events": events, "count": len(events)}

    search_events.__name__ = f"csv_search_{category}_events"
    return search_events


def build_category_schemas() -> list[dict]:
    properties = {
        "case_id": {"type": "string", "description": "Oncology CSV case_id"},
        "subject": {"type": "string", "description": "Exact event subject filter"},
        "feature_name": {"type": "string", "description": "Exact feature name filter"},
        "event_date": {"type": "string", "description": "Exact date or inclusive start..end range"},
        "group_id": {"type": "string", "description": "Exact event group filter"},
        "limit": {"type": "integer", "description": "Maximum events to return", "default": 100},
    }
    schemas = []
    for category, name, english in CATEGORY_TOOL_SPECS:
        schemas.append({
            "name": name,
            "description": f"Search oncology CSV {category} ({english}) events. Returns subject-feature-value rows with source metadata.",
            "parameters": {"type": "object", "properties": properties, "required": ["case_id"]},
        })
    return schemas


def register_category_tools(registry, data_root: Path) -> None:
    store = CsvEventStore(data_root)
    for (category, name, _), schema in zip(CATEGORY_TOOL_SPECS, build_category_schemas()):
        registry.register(name, make_category_tool(category, store), schema)
