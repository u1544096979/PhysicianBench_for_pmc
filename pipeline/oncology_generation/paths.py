from __future__ import annotations

from pathlib import Path


def safe_case_path(root: Path, case_id: object) -> Path:
    """Return a case child path that cannot escape root."""
    raw_case_id = str(case_id)
    normalized_case_id = raw_case_id.strip()
    if (
        not normalized_case_id
        or raw_case_id != normalized_case_id
        or normalized_case_id in {".", ".."}
        or "/" in normalized_case_id
        or "\\" in normalized_case_id
        or Path(normalized_case_id).is_absolute()
        or Path(normalized_case_id).name != normalized_case_id
    ):
        raise ValueError("case_id must be a safe case_id filename")

    root = Path(root)
    candidate = root / normalized_case_id
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("case_id must be a safe case_id filename within root") from exc
    return candidate
