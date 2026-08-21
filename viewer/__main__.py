"""`uv run python -m viewer` 启动本地轨迹浏览服务（默认 127.0.0.1:8765）。

spec: 2026-08-21-trajectory-viewer-design.md §4.2
"""
from __future__ import annotations

import uvicorn

from viewer.server import app


def main() -> int:
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
