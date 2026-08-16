import csv
from pathlib import Path

import pytest

from data.oncology_complete_trajectory.index.build_index import REQUIRED_COLUMNS
from tools.csv_event_store import CsvEventStore
from tools.csv_event_types import EventQuery


def _write_case(root: Path) -> None:
    root.mkdir(parents=True)
    rows = [
        {**{column: "" for column in REQUIRED_COLUMNS}, "case_id": "case-1", "event_date": "2024-02-01", "encnt_no": "2", "group_id": "g2", "category": "检验", "subject": "血液", "feature_name": "白细胞", "value": "3"},
        {**{column: "" for column in REQUIRED_COLUMNS}, "case_id": "case-1", "event_date": "2024-01-01", "encnt_no": "1", "group_id": "g1", "category": "诊断", "subject": "患者", "feature_name": "诊断名称", "value": "淋巴瘤"},
        {**{column: "" for column in REQUIRED_COLUMNS}, "case_id": "case-1", "event_date": "2024-03-01", "encnt_no": "3", "group_id": "g3", "category": "检验", "subject": "血液", "feature_name": "白细胞", "value": "4"},
    ]
    with (root / "case-1.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def test_query_filters_and_orders_events(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    _write_case(raw)
    store = CsvEventStore(tmp_path)
    events = store.query(EventQuery("case-1", category="检验", subject="血液", feature_name="白细胞", event_date="2024-01-01..2024-12-31"))
    assert [event["value"] for event in events] == ["3", "4"]
    assert events[0]["_source_row"] == "2"


def test_limit_and_no_match(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    _write_case(raw)
    store = CsvEventStore(tmp_path)
    assert len(store.query(EventQuery("case-1", category="检验", limit=1))) == 1
    assert store.query(EventQuery("case-1", category="手术")) == []


def test_query_validates_inputs_and_missing_case(tmp_path: Path):
    store = CsvEventStore(tmp_path)
    with pytest.raises(ValueError, match="Unsupported"):
        store.query(EventQuery("case-1", category="不存在"))
    with pytest.raises(ValueError, match="positive"):
        store.query(EventQuery("case-1", limit=0))
    with pytest.raises(KeyError):
        store.query(EventQuery("missing"))


def test_query_rejects_case_symlink_outside_data_root(tmp_path: Path):
    raw_root = tmp_path / "raw" / "csv"
    cleaned_root = tmp_path / "cleaned"
    _write_case(raw_root)
    cleaned_root.mkdir()
    (cleaned_root / "case-1.csv").symlink_to(raw_root / "case-1.csv")

    store = CsvEventStore(cleaned_root)

    with pytest.raises(KeyError, match="outside oncology CSV data root"):
        store.query(EventQuery("case-1"))
