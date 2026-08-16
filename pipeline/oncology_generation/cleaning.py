from __future__ import annotations

import csv
from pathlib import Path

from .nodes import build_event_groups
from .schemas import CleaningResult


def materialize_cleaned_case(
    source_csv: Path, cleaned_csv: Path, target_group_id: str
) -> CleaningResult:
    source_csv = Path(source_csv)
    cleaned_csv = Path(cleaned_csv)
    with source_csv.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames or []
        if not fieldnames:
            raise ValueError(f"source CSV has no header: {source_csv}")
        events = []
        for source_row, row in enumerate(reader, start=2):
            event = {field: row.get(field, "") or "" for field in fieldnames}
            event["_source_row"] = str(source_row)
            events.append(event)

    groups = build_event_groups(events)
    target_index = next(
        (index for index, group in enumerate(groups) if group.group_id == target_group_id),
        None,
    )
    if target_index is None:
        raise ValueError(f"target group not found: {target_group_id}")

    retained_group_ids = {group.group_id for group in groups[:target_index]}
    retained_events = [event for event in events if event.get("group_id", "") in retained_group_ids]
    target_events = groups[target_index].events

    cleaned_csv.parent.mkdir(parents=True, exist_ok=True)
    with cleaned_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(retained_events)

    return CleaningResult(
        cleaned_csv=cleaned_csv,
        target_group_id=target_group_id,
        target_events=target_events,
    )
