from __future__ import annotations
import uuid

from . import catalog

CSV_FIELDS = ("case_id", "encnt_no", "group_id", "subject", "feature_name",
              "feature_code", "feature_type", "value", "actual_value", "extra_value",
              "unit", "method", "source", "_record_source", "event_date",
              "category", "pipeline_version")

_CSV_KEYS = set(CSV_FIELDS)


def _feat_type(category, conv) -> str:
    ft = (conv.get("feature_type") or "").strip()
    return ft if ft in catalog.FEATURE_TYPES else catalog.CATEGORY_FEATURE_TYPE_FALLBACK[category][0]


def _row(context, *, category, feature_name, value, unit, event_date,
         subject=None, method=None, feature_type=None, actual_value="",
         extra_value="", layer=None, episode_id=None, feature_code="") -> dict:
    conv = context.convention_by_category[category]
    feature_type = feature_type or _feat_type(category, conv)
    cf = {
        "case_id": context.case_id,
        "encnt_no": context.encnt_no or "",
        "group_id": str(uuid.uuid4()),
        "subject": subject or conv.get("subject", ""),
        "feature_name": feature_name or "",
        "feature_code": feature_code,
        "feature_type": feature_type,
        "value": value or "",
        "actual_value": actual_value,
        "extra_value": extra_value,
        "unit": unit or "",
        "method": method if method is not None else conv.get("method", ""),
        "source": conv.get("source", ""),
        "_record_source": conv.get("_record_source", ""),
        "event_date": event_date or "",
        "category": category,
        "pipeline_version": conv.get("pipeline_version", ""),
    }
    row = {"csv_fields": cf, "group_id": cf["group_id"],
           "category": category, "feature_name": feature_name, "value": str(value or ""),
           "event_date": event_date or "", "layer": layer, "episode_id": episode_id}
    return row


def materialize(context, plan) -> list[dict]:
    rows: list[dict] = []
    for la in plan.get("layer_a", []) or []:
        cat = la.get("category", "")
        if cat not in catalog.ALLOWED_CATEGORIES:
            continue
        rows.append(_row(
            context, category=cat, feature_name=la.get("feature_name", ""),
            value=la.get("value", ""), unit=la.get("unit", ""),
            event_date=la.get("event_date", ""), layer="A",
        ))
    for ep in plan.get("episodes", []) or []:
        eid = ep.get("episode_id") or f"ep{ep['days'][0].get('date_abs','')}"
        for day in ep.get("days", []) or []:
            cat = day.get("category", "")
            if cat not in catalog.ALLOWED_CATEGORIES:
                continue
            rows.append(_row(
                context, category=cat, feature_name=day.get("feature_name", ""),
                value=day.get("value", ""), unit=day.get("unit", ""),
                event_date=day.get("date_abs", ""), layer="B", episode_id=eid,
            ))
    return rows


def csv_row(row: dict) -> dict:
    """17 字段 CSV 行（去掉 _layer/_episode_id 等元字段）."""
    return {k: row["csv_fields"].get(k, "") for k in CSV_FIELDS}
