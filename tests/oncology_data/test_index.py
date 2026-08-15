import csv
import json
from pathlib import Path

import pytest

from data.oncology_complete_trajectory.index.build_index import (
    REQUIRED_COLUMNS,
    build_index,
    load_case_csv,
)


def _write_case(path: Path, case_id: str, rows: int = 2) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with (path / f"{case_id}.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(REQUIRED_COLUMNS))
        writer.writeheader()
        for i in range(rows):
            writer.writerow({**{column: "" for column in REQUIRED_COLUMNS}, "case_id": case_id, "category": "检验"})


def test_build_index_discovers_files_and_counts(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    _write_case(raw, "case-a", 2)
    _write_case(raw, "case-b", 3)
    manifest = build_index(tmp_path)
    assert manifest["file_count"] == 2
    assert manifest["row_count"] == 5
    assert manifest["category_counts"] == {"检验": 5}
    assert len(manifest["files"]) == 2
    assert (tmp_path / "index" / "manifest.json").is_file()


def test_header_validation_rejects_missing_required_column(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    with (raw / "bad.csv").open("w", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=[c for c in REQUIRED_COLUMNS if c != "category"]).writeheader()
    with pytest.raises(ValueError, match="category"):
        build_index(tmp_path)


def test_load_case_csv_rejects_unknown_id(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    _write_case(raw, "known")
    assert load_case_csv("known", tmp_path).name == "known.csv"
    with pytest.raises(KeyError, match="missing"):
        load_case_csv("missing", tmp_path)

