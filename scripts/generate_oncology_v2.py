"""OncoBench v2 任务生成 CLI.

用法:
    python -m scripts.generate_oncology_v2 --pilot 5
    python -m scripts.generate_oncology_v2 --cases <id1> <id2>
    python -m scripts.generate_oncology_v2 --all
选项:
    --relabel          强制重新标注（默认已有标注结果则跳过）
    --data-root PATH   原始CSV目录（默认 data/oncology_complete_trajectory/raw/csv）
    --output-root PATH 任务输出目录（默认 tasks/oncology-v2）
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.oncology_generation.graph import run_case  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OncoBench v2 任务生成流水线")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pilot", type=int, metavar="N", help="取前N个case（pilot试跑）")
    group.add_argument("--cases", nargs="+", metavar="ID", help="指定case_id列表")
    group.add_argument("--all", action="store_true", help="全量case")
    parser.add_argument("--relabel", action="store_true", help="强制重新标注")
    parser.add_argument("--data-root", type=Path, default=PROJECT_ROOT / "data/oncology_complete_trajectory/raw/csv")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "tasks/oncology-v2")
    return parser.parse_args(argv)


def select_case_ids(args: argparse.Namespace, data_root: Path) -> list[str]:
    csv_files = sorted(p for p in data_root.glob("*.csv") if p.name != "index.csv")
    if args.pilot is not None:
        files = csv_files[: args.pilot]
    elif args.cases:
        wanted = {c if c.endswith(".csv") else f"{c}.csv" for c in args.cases}
        files = [p for p in csv_files if p.name in wanted]
        missing = wanted - {p.name for p in files}
        if missing:
            raise SystemExit(f"未找到case: {sorted(missing)}")
    else:
        files = csv_files
    return [p.stem for p in files]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    data_root: Path = args.data_root
    generated_root = PROJECT_ROOT / "generated/v2"

    case_ids = select_case_ids(args, data_root)
    print(f"共 {len(case_ids)} 个case；数据源 {data_root}")
    print(f"任务输出 {args.output_root}；中间产物 {generated_root}")

    stats = {"persisted": [], "review_queue": [], "error": []}
    t0 = time.time()
    for i, case_id in enumerate(case_ids, start=1):
        print(f"\n[{i}/{len(case_ids)}] case {case_id} ...", flush=True)
        try:
            final = run_case(
                case_id,
                data_root=data_root,
                output_root=args.output_root,
                generated_root=generated_root,
                force_relabel=args.relabel,
            )
            status = final.get("status", "error")
            if status not in stats:
                status = "error"
            stats[status].append(case_id)
            label = final.get("label")
            rec = label.recommended_type if label else "?"
            print(f"  -> {status} (推荐类型: {rec})", flush=True)
        except Exception as exc:  # noqa: BLE001 单case失败不阻断批量
            stats["error"].append(case_id)
            print(f"  -> error: {exc}", flush=True)

    elapsed = time.time() - t0
    print(f"\n========== 完成（{elapsed:.0f}s） ==========")
    print(f"persisted    {len(stats['persisted'])}: {stats['persisted']}")
    print(f"review_queue {len(stats['review_queue'])}: {stats['review_queue']}")
    print(f"error        {len(stats['error'])}: {stats['error']}")
    return 0 if not stats["error"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
