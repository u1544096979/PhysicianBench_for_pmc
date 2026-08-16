"""Build and query a lightweight, read-only index for oncology CSV files."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

# These are the fields needed by the CSV event store.  Source files may carry
# additional columns; indexing never rewrites or normalizes those files.
REQUIRED_COLUMNS = (
    "case_id",
    "encnt_no",
    "group_id",
    "subject",
    "feature_name",
    "feature_type",
    "value",
    "actual_value",
    "extra_value",
    "unit",
    "method",
    "source",
    "_record_source",
    "event_date",
    "category",
    "pipeline_version",
)


def _csv_directory(data_root: Path) -> Path:
    root = Path(data_root)
    candidate = root / "raw" / "csv"
    return candidate if candidate.is_dir() else root


def _manifest_path(data_root: Path) -> Path:
    root = Path(data_root)
    return (root.parent / "index" / "manifest.json") if root.name == "csv" else (root / "index" / "manifest.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_csv(path: Path) -> tuple[int, dict[str, int]]:
    categories: dict[str, int] = {}
    rows = 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        header = reader.fieldnames or []
        missing = [column for column in REQUIRED_COLUMNS if column not in header]
        if missing:
            raise ValueError(f"CSV header missing required columns in {path}: {', '.join(missing)}")
        for row in reader:
            rows += 1
            category = (row.get("category") or "").strip()
            categories[category] = categories.get(category, 0) + 1
    return rows, categories


def build_index(data_root: Path) -> dict[str, Any]:
    """Scan CSVs and write a manifest without materializing a combined dataset."""
    root = Path(data_root)
    csv_dir = _csv_directory(root)
    if not csv_dir.is_dir():
        raise FileNotFoundError(f"CSV data directory does not exist: {csv_dir}")

    files: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    row_count = 0
    for path in sorted(csv_dir.glob("*.csv")):
        rows, categories = _inspect_csv(path)
        row_count += rows
        for category, count in categories.items():
            category_counts[category] = category_counts.get(category, 0) + count
        files.append(
            {
                "case_id": path.stem,
                "path": str(path),
                "row_count": rows,
                "sha256": _sha256(path),
            }
        )

    manifest = {
        "data_root": str(csv_dir),
        "file_count": len(files),
        "row_count": row_count,
        "category_counts": dict(sorted(category_counts.items())),
        "files": files,
    }
    target = _manifest_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_case_csv(case_id: str, data_root: Path) -> Path:
    """Return the source CSV for ``case_id``; reject unknown IDs."""
    csv_dir = _csv_directory(Path(data_root))
    if not case_id or Path(case_id).name != case_id or Path(case_id).suffix:
        raise KeyError(f"Invalid oncology case id: {case_id}")
    path = csv_dir / f"{case_id}.csv"
    if not path.is_file():
        raise KeyError(f"Unknown oncology case id: {case_id}")
    return path


if __name__ == "__main__":  # pragma: no cover - convenience for data setup
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", nargs="?", type=Path, default=Path("data/oncology_complete_trajectory"))
    args = parser.parse_args()
    print(json.dumps(build_index(args.data_root), ensure_ascii=False, indent=2))
