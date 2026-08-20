"""OncoBench 轨迹浏览 FastAPI 应用：3 个 JSON API + 静态挂载。

spec: 2026-08-21-trajectory-viewer-design.md §4.2 server.py
"""
from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from viewer import scanner

DEFAULT_ROOT = Path(os.environ.get("VIEWER_ROOT", "tasks/oncology-v2"))
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(root: Path | None = None) -> FastAPI:
    scan_root = Path(root) if root is not None else DEFAULT_ROOT
    app = FastAPI(title="OncoBench Trajectory Viewer")

    @app.get("/api/tasks")
    def list_tasks():
        return [asdict(t) for t in scanner.scan_tasks(scan_root)]

    @app.get("/api/tasks/{case_id}")
    def task_detail(case_id: str):
        if not (scan_root / case_id).is_dir():
            raise HTTPException(status_code=404, detail=f"case 不存在: {case_id}")
        return asdict(scanner.load_task(scan_root, case_id))

    @app.get("/api/tasks/{case_id}/runs/{run_id}")
    def run_detail(case_id: str, run_id: str):
        if not (scan_root / case_id / "runs" / run_id).is_dir():
            raise HTTPException(status_code=404, detail=f"run 不存在: {run_id}")
        return asdict(scanner.load_run(scan_root, case_id, run_id))

    if STATIC_DIR.is_dir():
        # 静态挂载必须在 API 路由之后，作兜底；index.html 由 Task 5 提供。
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    return app


app = create_app()
