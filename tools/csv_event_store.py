"""Read-only, deterministic queries over one oncology case CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from data.oncology_complete_trajectory.index.build_index import load_case_csv

from .csv_event_types import EVENT_COLUMNS, EventQuery


class CsvEventStore:
    def __init__(self, data_root: Path):
        self.data_root = Path(data_root)

    def query(self, query: EventQuery) -> list[dict[str, str]]:
        query.validate()
        path = load_case_csv(query.case_id, self.data_root)
        matches: list[tuple[tuple[str, str, str, int], dict[str, str]]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            missing = [field for field in EVENT_COLUMNS if field not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"CSV header missing required columns: {', '.join(missing)}")
            for row_number, row in enumerate(reader, start=2):
                if query.category is not None and row["category"] != query.category:
                    continue
                if query.subject is not None and row["subject"] != query.subject:
                    continue
                if query.feature_name is not None and row["feature_name"] != query.feature_name:
                    continue
                if query.group_id is not None and row["group_id"] != query.group_id:
                    continue
                if query.event_date is not None and not _date_matches(row["event_date"], query.event_date):
                    continue
                event = {field: row.get(field, "") or "" for field in EVENT_COLUMNS}
                event["_source_row"] = str(row_number)
                key = (event["event_date"], event["encnt_no"], event["group_id"], row_number)
                matches.append((key, event))
        matches.sort(key=lambda item: item[0])
        return [event for _, event in matches[: query.limit]]


def _date_matches(value: str, selector: str) -> bool:
    if ".." not in selector:
        return value == selector
    start, end = selector.split("..", 1)
    return (not start or value >= start) and (not end or value <= end)
