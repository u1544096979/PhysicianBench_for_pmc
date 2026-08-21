"""存量 v2 任务噪声注入批处理脚本.

用法:
    python -m scripts.apply_noise --dry-run
    python -m scripts.apply_noise --limit 20
    python -m scripts.apply_noise --case-ids <id1> <id2>
    python -m scripts.apply_noise --resume        # 仅跳过已完成的 noisy case
选项:
    --dry-run    只跑闸门不写盘（静默）
    --resume     仅跳过已完成且 final_status 为 noisy 的 case（degraded_clean/损坏 manifest 会重试）
    --limit N    最多处理 N 个
    --case-ids   指定 case_id 列表
    --workers 1  默认串行
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from llm.client import get_default_client
from pipeline.noise_injection.config import NoiseConfig
from pipeline.noise_injection.context import case_from_csv
from pipeline.noise_injection.injection import run_injection
from pipeline.noise_injection.manifest import read_manifest, write_manifest
from pipeline.noise_injection.materialize import CSV_FIELDS
from pipeline.oncology_generation.paths import safe_case_path
from pipeline.oncology_generation.schemas import build_event_groups, serialize_groups

SRC_ROOT = PROJECT_ROOT / "tasks/oncology-v2"
OUT_ROOT = PROJECT_ROOT / "tasks/oncology-v2-noisy"
RAW_ROOT = PROJECT_ROOT / "data/oncology_complete_trajectory/raw/csv"
QUEUE_PATH = PROJECT_ROOT / "generated/v2/review_queue.jsonl"

_CLEAN_FILENAMES = ("instruction.md", "task.toml", "ground_truth.json", "checkpoints.json")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="存量 v2 任务噪声注入")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--case-ids", nargs="+", metavar="ID", default=None)
    p.add_argument("--workers", type=int, default=1)
    return p.parse_args(argv)


def select_task_ids(src_root: Path, case_ids=None, limit=None) -> list[str]:
    dirs = sorted(p.name for p in src_root.iterdir()
                  if p.is_dir() and (p / "task.toml").exists())
    if case_ids:
        wanted = set(case_ids)
        dirs = [d for d in dirs if d in wanted]
        missing = wanted - set(dirs)
        if missing:
            raise SystemExit(f"未找到 task: {sorted(missing)}")
    if limit is not None:
        dirs = dirs[:limit]
    return dirs


def _is_completed_noisy(noise_dir: Path) -> bool:
    """仅当 manifest 存在、可读且 final_status == "noisy" 时视为已完成（可跳过）."""
    path = noise_dir / "noise_manifest.json"
    if not path.exists():
        return False
    try:
        manifest = read_manifest(path)
    except (OSError, ValueError):  # 损坏/不可读 manifest 不跳过，重试
        return False
    return isinstance(manifest, dict) and manifest.get("final_status") == "noisy"


def _task_payload(src_dir: Path):
    toml = (src_dir / "task.toml").read_text(encoding="utf-8")
    gt = json.loads((src_dir / "ground_truth.json").read_text(encoding="utf-8"))
    instruction = (src_dir / "instruction.md").read_text(encoding="utf-8")
    return toml, gt, instruction


def _load_cleaned(cleaned_path: Path) -> tuple[list[str], list[dict], str]:
    """读源任务 cleaned_trajectory.csv.

    返回 (fieldnames, 数据行列表, 干净可见事件文本)。
    可见事件文本按 agent 视角渲染（与流水线 solve 一致）：
    build_event_groups + serialize_groups(full=True)，_source_row 按 CSV 行号（含表头从2计）.
    """
    events: list[dict] = []
    rows: list[dict] = []
    with cleaned_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or CSV_FIELDS)
        for source_row, row in enumerate(reader, start=2):
            rows.append(row)
            event = {k: (v or "") for k, v in row.items() if k}
            event["_source_row"] = str(source_row)
            events.append(event)
    visible_text = serialize_groups(build_event_groups(events), full=True)
    return fieldnames, rows, visible_text


def process_case(case_id: str, *, client, dry_run: bool, noise_dir_exists: bool) -> dict:
    src_dir = SRC_ROOT / safe_case_path(SRC_ROOT, case_id)
    raw = RAW_ROOT / f"{case_id}.csv"
    _toml, gt, instruction = _task_payload(src_dir)
    task_type = gt.get("task_type", "")
    target_group_id = gt.get("target_group_id", "")
    target_date = gt.get("target_date", "")
    ground_truth = gt.get("ground_truth", {})
    ctx = case_from_csv(case_id, raw, task_type=task_type,
                        target_group_id=target_group_id, target_date=target_date,
                        instruction=instruction, ground_truth=ground_truth)
    # 源任务 cleaned csv：数据行 + 干净可见事件文本（闸门3求解必须看到真实可见事件，
    # 而非 case_facts_text 存根）；noise_start_row = 最终 noisy CSV 中首条噪声行的
    # 1-based 绝对行号（表头1行 + 原始数据行 + 1）
    cleaned_src = src_dir / "cleaned_trajectory.csv"
    fieldnames, orig, visible_text = _load_cleaned(cleaned_src)
    noise_start_row = len(orig) + 2
    result = run_injection(ctx, NoiseConfig(), client, visible_text=visible_text,
                           full_attempts=1 if dry_run else None,
                           noise_start_row=noise_start_row)
    # 写 review_queue（降级）
    if not dry_run and result.review_queue_entries:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with QUEUE_PATH.open("a", encoding="utf-8") as fh:
            for entry in result.review_queue_entries:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if dry_run:
        return {"case_id": case_id, "dry_run_status": result.final_status,
                "rows_passed": len(result.rows)}
    out_dir = OUT_ROOT / safe_case_path(OUT_ROOT, case_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 复制干净文件（原样不动，同目录内容不改）
    for name in _CLEAN_FILENAMES:
        src = src_dir / name
        if src.exists():
            dst = out_dir / name
            if not dst.exists():  # 避免每次覆盖造成非幂等
                dst.write_bytes(src.read_bytes())
    # cleaned：原始行 + 噪声行（原版 cleaned 即"干净版"）
    cleaned_dst = out_dir / "cleaned_trajectory.csv"
    if result.rows:
        with cleaned_dst.open("w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            wr.writeheader()
            wr.writerows(orig)
            for r in result.rows:
                wr.writerow({k: r.get(k, "") for k in fieldnames})
    else:
        cleaned_dst.write_bytes(cleaned_src.read_bytes())
    write_manifest(out_dir / "noise_manifest.json", result.manifest)
    return {"case_id": case_id, "final_status": result.final_status,
            "rows_passed": len(result.rows)}


def main(argv=None) -> int:
    args = parse_args(argv)
    client = get_default_client(PROJECT_ROOT / "generated/v2/trace")
    ids = select_task_ids(SRC_ROOT, case_ids=args.case_ids, limit=args.limit)
    print(f"共 {len(ids)} 个存量任务；输出 {OUT_ROOT}")
    stats = {"noisy": 0, "degraded_clean": 0, "skipped": 0, "error": []}
    detail: list[dict] = []
    t0 = time.time()
    for i, cid in enumerate(ids, start=1):
        noise_dir = OUT_ROOT / safe_case_path(OUT_ROOT, cid)
        completed = args.resume and _is_completed_noisy(noise_dir)
        if completed:
            stats["skipped"] += 1
            continue
        try:
            res = process_case(cid, client=client, dry_run=args.dry_run,
                               noise_dir_exists=(noise_dir / "noise_manifest.json").exists())
            stats[res["final_status"] if not args.dry_run else res["dry_run_status"]] += 1
            detail.append(res)
        except Exception as exc:  # noqa: BLE001  单 case 失败不中断批处理
            stats["error"].append(cid)
            detail.append({"case_id": cid, "error": str(exc)})
    done = time.time() - t0
    summary = OUT_ROOT / "apply_noise_report.jsonl" if not args.dry_run else \
        SRC_ROOT.parent / "apply_noise_dryrun.jsonl"
    summary.parent.mkdir(parents=True, exist_ok=True)
    with summary.open("a", encoding="utf-8") as fh:
        for d in detail:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"完成({done:.0f}s) noisy={stats['noisy']} degraded_clean={stats['degraded_clean']} "
          f"skipped={stats['skipped']} error={stats['error']}")
    return 0 if not stats["error"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
