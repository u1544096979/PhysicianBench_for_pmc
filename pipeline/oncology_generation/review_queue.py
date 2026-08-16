from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class ReviewItem:
    case_id: str
    errors: list[str]
    state_path: str


def append_review_item(path: Path, item: ReviewItem) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
