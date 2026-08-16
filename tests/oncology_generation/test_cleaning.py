import csv
from pathlib import Path

import pytest

from pipeline.oncology_generation.cleaning import materialize_cleaned_case


HEADER = ["case_id", "group_id", "event_date", "category", "feature_name", "value"]


def _row(group_id: str, date: str, category: str, value: str) -> dict[str, str]:
    return {
        "case_id": "case-1",
        "group_id": group_id,
        "event_date": date,
        "category": category,
        "feature_name": "诊断名称",
        "value": value,
    }


def test_materialize_cleaned_case_removes_target_and_following_groups(tmp_path: Path):
    source = tmp_path / "raw.csv"
    cleaned = tmp_path / "nested" / "cleaned.csv"
    rows = [
        _row("g1", "2024-01-01", "诊断", "A"),
        _row("g2", "2024-01-02", "诊断", "B"),
        _row("g2", "2024-01-02", "诊断", "B-分期"),
        _row("g3", "2024-01-02", "病理", "C"),
    ]
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
    original = source.read_bytes()

    result = materialize_cleaned_case(source, cleaned, target_group_id="g2")

    assert [event["group_id"] for event in result.target_events] == ["g2", "g2"]
    assert [event["_source_row"] for event in result.target_events] == ["3", "4"]
    with cleaned.open(encoding="utf-8", newline="") as stream:
        written = list(csv.DictReader(stream))
    assert [row["group_id"] for row in written] == ["g1"]
    assert source.read_bytes() == original


def test_materialize_cleaned_case_rejects_unknown_target(tmp_path: Path):
    source = tmp_path / "raw.csv"
    source.write_text("group_id,event_date,category\ng1,2024-01-01,诊断\n", encoding="utf-8")

    try:
        materialize_cleaned_case(source, tmp_path / "cleaned.csv", target_group_id="missing")
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("unknown target group should fail")


def test_materialize_cleaned_case_rejects_same_source_and_destination(tmp_path: Path):
    source = tmp_path / "raw.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADER)
        writer.writeheader()
        writer.writerow(_row("g1", "2024-01-01", "诊断", "A"))

    with pytest.raises(ValueError, match="source_csv and cleaned_csv must differ"):
        materialize_cleaned_case(source, source, target_group_id="g1")


def test_materialize_cleaned_case_rejects_symlink_before_overwriting_external_file(tmp_path: Path):
    source = tmp_path / "raw.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADER)
        writer.writeheader()
        writer.writerow(_row("g1", "2024-01-01", "诊断", "A"))

    external = tmp_path / "external.csv"
    external.write_text("do not overwrite\n", encoding="utf-8")
    cleaned_root = tmp_path / "cleaned"
    cleaned_root.mkdir()
    cleaned = cleaned_root / "case.csv"
    cleaned.symlink_to(external)

    with pytest.raises(ValueError, match="outside cleaned root|symlink"):
        materialize_cleaned_case(source, cleaned, target_group_id="g1")

    assert external.read_text(encoding="utf-8") == "do not overwrite\n"
