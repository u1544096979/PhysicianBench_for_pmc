from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path

from .nodes import build_event_groups
from .schemas import CleaningResult


def materialize_cleaned_case(
    source_csv: Path,
    cleaned_csv: Path,
    target_group_id: str,
    answer_event_rows: list[int] | None = None,
    cleaned_root: Path | None = None,
) -> CleaningResult:
    """事件级/整组两档清洗。

    - answer_event_rows 为空：整组删除（target组及其后全部删除，旧行为）
    - answer_event_rows 非空：target组内仅删除答案事件行；target组之后的组仍全部删除。
      注意：此处行号基于"数据行从1计"（与 nodes.load_and_timeline 注入一致），
      而本函数读CSV时是从2计（含表头），因此做 +1 对齐。
    """
    source_csv = Path(source_csv)
    cleaned_csv = Path(cleaned_csv)
    same_path = source_csv.resolve() == cleaned_csv.resolve()
    if not same_path and source_csv.exists() and cleaned_csv.exists():
        same_path = os.path.samefile(source_csv, cleaned_csv)
    if same_path:
        raise ValueError("source_csv and cleaned_csv must differ")

    output_root = Path(cleaned_root) if cleaned_root is not None else cleaned_csv.parent
    if output_root.is_symlink():
        raise ValueError(f"cleaned root must not be a symlink: {output_root}")
    if cleaned_csv.is_symlink():
        raise ValueError(f"cleaned output must not be a symlink: {cleaned_csv}")
    resolved_root = output_root.resolve()
    try:
        cleaned_csv.resolve().relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"cleaned output resolves outside cleaned root: {cleaned_csv}") from exc

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

    if answer_event_rows:
        # 事件级：target组内保留证据性事件（行号对齐：CSV含表头，_source_row从2起）
        hide = {str(r + 1) for r in answer_event_rows}
        kept_target = [
            ev for ev in target_events
            if ev.get("_source_row", "") not in hide
        ]
        target_events = [ev for ev in target_events if ev.get("_source_row", "") in hide]
        retained_events = retained_events + kept_target

    cleaned_csv.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=cleaned_csv.parent,
        prefix=f".{cleaned_csv.stem}.",
        suffix=".tmp",
        delete=False,
    )
    staged_csv = Path(temporary_file.name)
    try:
        with temporary_file as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(retained_events)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        staged_csv.unlink(missing_ok=True)
        raise

    return CleaningResult(
        cleaned_csv=staged_csv,
        target_group_id=target_group_id,
        target_events=target_events,
    )
