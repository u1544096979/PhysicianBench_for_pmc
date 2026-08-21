from __future__ import annotations
import json
from pathlib import Path

MANIFEST_SCHEMA_VERSION = 1


def build_manifest(*, case_id: str, task_type: str, generated_at: str,
                   config_snapshot: dict, attempts: list[dict],
                   final_status: str, rows: list[dict], degrade_reason=None) -> dict:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "case_id": case_id,
        "task_type": task_type,
        "generated_at": generated_at,
        "config_snapshot": config_snapshot,
        "attempts": attempts,
        "final_status": final_status,
        "degrade_reason": degrade_reason,
        "rows": rows,
    }


def write_manifest(path, manifest: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def read_manifest(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
