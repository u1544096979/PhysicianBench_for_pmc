# 本地轨迹浏览服务（trajectory viewer）+ 旧 jobs 约定清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个零构建、一条命令启动的本地 Web 服务（`viewer/`），用于浏览 `tasks/oncology-v2/*/runs/*` 的完整评测轨迹；同时清除已死的旧 `jobs/` 约定代码。

**Architecture:** 纯 Python 单包三模块 —— `scanner.py` 是只读纯函数层（目录 → dataclass，可单测，无 FastAPI 依赖）；`server.py` 是 FastAPI 应用（3 个 JSON API + 静态文件挂载）；`__main__.py` 用 uvicorn 绑 `127.0.0.1:8765`。前端是无构建的原生 HTML/JS/CSS 单页（`viewer/static/`），每次请求都现读磁盘（手动刷新语义）。

**Tech Stack:** Python ≥3.10（venv 实为 3.13，`tomllib` 可用）、FastAPI、uvicorn、markdown、httpx（测试）。用 `uv` 管理依赖。

## Global Constraints

- 依赖通过 `uv add fastapi uvicorn markdown` 添加（httpx 已由 openai 传递引入，测试直接可用）。
- 服务只绑 `127.0.0.1:8765`，不做鉴权、不做 WebSocket/轮询。
- 扫描范围固定为 `tasks/oncology-v2`（默认根目录）；scanner API 一律接收 `Path` 根目录参数，保留扩展点，不写死其他任务集。
- `scanner.py` 只读产物文件，**绝不修改** case/run 目录；每次调用现读，不做内存缓存。
- 所有读写用 `encoding="utf-8"`；`json.dumps(..., ensure_ascii=False)` 以便中文可读。
- 前端零构建（无 node），纯原生 HTML/JS/CSS，不引入任何框架 CDN。
- 不动 `website/`、不动 `eval/runner.py` 产物格式、不动 `docs/superpowers/plans/` 历史记录、不动 `.github/workflows/deploy.yml`。
- 不提交 `data/oncology_complete_trajectory/prompt_test/`（实验临时数据）。
- 验收命令：`git grep -n "job_manager\|score_jobs\|run_batch_task"` 无残留（`-- . ':!.venv'` 除外）；全量 `uv run pytest` 通过。

---

## 文件结构总览

**删除（7 个文件，Task 1）：**
- `scripts/job_manager.py`、`scripts/score_jobs.py`、`scripts/run_batch_task.sh`、`scripts/task_taxonomy_v1.json`、`scripts/run_task.py`
- `tests/oncology_runtime/test_run_task_csv.py`、`tests/oncology_runtime/test_local_runner.py`

**修改：**
- `README.md`（Task 1 目录结构 + 快速开始；Task 6 viewer 入口）
- `agent/trajectory.py`（Task 1 docstring）
- `docs/physicianbench-study/README.md`（Task 1 把已删脚本引用标注 legacy）
- `pyproject.toml`（Task 2 由 `uv add` 更新）

**新建：**
- `viewer/__init__.py`、`viewer/scanner.py`、`viewer/server.py`、`viewer/__main__.py`（Task 2/3/4）
- `viewer/static/index.html`、`viewer/static/app.js`、`viewer/static/style.css`（Task 5）
- `tests/test_viewer_scanner.py`、`tests/test_viewer_server.py`（Task 3/4）

**交互接口（各 Task 之间的契约）：**

| 符号 | 签名 | 定义处 | 消费处 |
|---|---|---|---|
| `scan_tasks(root: Path) -> list[TaskInfo]` | 遍历 `root/*/`，读 task.toml + 统计 runs | scanner | server `/api/tasks` |
| `load_task(root: Path, case_id: str) -> TaskDetail` | instruction + checkpoints + runs 列表 | scanner | server `/api/tasks/{case_id}` |
| `load_run(root: Path, case_id: str, run_id: str) -> RunDetail` | scorecard + trajectory + 报告 + gt + CSV | scanner | server `/api/tasks/{case_id}/runs/{run_id}` |
| `create_app(root: Path | None) -> FastAPI` | 应用工厂，root 可注入（测试传 tmp_path） | server | `__main__` + 测试 |
| `DEFAULT_ROOT` | `Path(os.environ.get("VIEWER_ROOT", "tasks/oncology-v2"))` | server | `create_app` 默认值 |
| `app: FastAPI` | 模块级单例 `create_app()` | server | `__main__.py` |
| dataclass 字段 | 见 Task 3 定义 | scanner | 前端 JSON 键名（`asdict`） |

---

### Task 1: 前置提交 + 清理旧 jobs 约定（G1）

**Files:**
- Delete: `scripts/job_manager.py`, `scripts/score_jobs.py`, `scripts/run_batch_task.sh`, `scripts/task_taxonomy_v1.json`, `scripts/run_task.py`, `tests/oncology_runtime/test_run_task_csv.py`, `tests/oncology_runtime/test_local_runner.py`
- Modify: `README.md`（目录结构 + 快速开始）、`agent/trajectory.py`（docstring）、`docs/physicianbench-study/README.md`

**Interfaces:**
- Consumes: 无（纯清理，不引入新模块）。
- Produces: 仓库内不再存在任何 `jobs/` 布局实现；为后续 `viewer/` 与 `eval/runner.py` 文档入口铺路。

**背景（必须照做——spec §7）：** main 上现有未提交改动属于另一项 eval-loop 收尾（`agent/mini_agent.py`、`agent/trajectory.py`、`generated/v2/*`、两个 case 的产物等）。此任务的第一步先把这些改动单独提交到 main，再开 `feat/trajectory-viewer` 分支；jobs 清理的提交落在新分支上。

- [ ] **Step 1: 先提交既有的 eval-loop 未提交改动（与本次无关）**

```bash
git checkout main
# 确认当前未提交改动。把 eval-loop 收尾相关文件加入并提交：
git add agent/mini_agent.py agent/trajectory.py \
        docs/superpowers/specs/2026-08-20-noise-injection-design.md \
        generated/v2/review_queue.jsonl \
        tasks/oncology-v2/00813296fa8d52f407df63d1539f6018/checkpoints.json \
        tasks/oncology-v2/00813296fa8d52f407df63d1539f6018/ground_truth.json
git commit -m "chore: eval-loop 收尾（runner 模型名/jiudge 签名/extra_body/产物）"
# 注意：uv.lock 与两个 case 的 runs/ 新产物、以及未跟踪的 20260820-210036 目录先不提交
# （uv.lock 留到 Task 2 随依赖更新一并处理；runs/ 是本次 viewer 的验收数据，提交与否见 Step 结尾说明）。
```

> 如果个别文件不在你的机器上（例如 `generated/v2/trace/llm_trace.jsonl` 属于运行期产物），用 `git checkout main && git status` 现场核对后逐个 `git add`；核心目标是「把不属于 jobs 清理的杂项改动先落一次独立提交」即可，不必逐字对齐上面的清单。

- [ ] **Step 2: 开分支**

```bash
git checkout -b feat/trajectory-viewer
```

- [ ] **Step 3: 删除 7 个文件**

```bash
git rm scripts/job_manager.py scripts/score_jobs.py scripts/run_batch_task.sh \
       scripts/task_taxonomy_v1.json scripts/run_task.py \
       tests/oncology_runtime/test_run_task_csv.py \
       tests/oncology_runtime/test_local_runner.py
```

- [ ] **Step 4: 修改 `agent/trajectory.py` docstring**

把文件头 docstring 第一段第二行：

```python
Consumed by `parse_trajectory.py` and `score_jobs.py` to compute
per-task tool-call counts and step-by-step playback.
```

替换为：

```python
Consumed by the trajectory viewer (`viewer/scanner.py`) to compute
per-task tool-call counts and step-by-step playback.
```

- [ ] **Step 5: 修改 `README.md` 目录结构**

找到「目录结构」代码块中这 4 行并删除：

```
│   ├── run_task.py                      # 单任务：Agent 运行 + pytest 评测
│   ├── run_batch_task.sh                # 批量运行（支持 --resume / --n_runs / --model）
│   ├── run_eval.py                      # 对 job 目录重跑诊断规则评估
│   ├── score_jobs.py                    # 汇总 pass@k / pass^k / 平均轮次
│   └── job_manager.py                   # job 目录管理（创建 / resume）
```

替换为（保留 run_eval.py，并新增 eval/ 与 viewer/ 条目）：

```
│   ├── run_eval.py                      # 对单个任务重跑诊断规则评估
├── eval/                                # 评测闭环（v2）
│   ├── runner.py                        # 单任务运行器：Agent 解题 + checkpoint 判分
│   └── checkpoint_executor.py           # checkpoint 执行（code / llm_judge / field_match）
├── viewer/                              # 本地轨迹浏览服务（零构建）
│   ├── __main__.py                      # uv run python -m viewer → 127.0.0.1:8765
│   ├── scanner.py                       # 只读扫描/解析纯函数层
│   ├── server.py                        # FastAPI：3 个 API + 静态挂载
│   └── static/                          # 原生 HTML/JS/CSS 单页
```

- [ ] **Step 6: 修改 `README.md` 快速开始**

把「快速开始」里的步骤 5/6/7 整段：

```
# 5. 运行单个任务（Agent 评测 + pytest）
uv run python scripts/run_task.py tasks/oncology-v1/<case_id> \
  --model <agent-model> --data-root data/oncology_complete_trajectory

# 6. 批量运行（交互式确认，产物写入 jobs/<batch>/<case_id>/）
bash scripts/run_batch_task.sh --model <agent-model> --reasoning-effort high
# 断点续跑：
bash scripts/run_batch_task.sh --resume jobs/<batch-dir>

# 7. 汇总分数
uv run python scripts/score_jobs.py jobs/<batch-dir>
uv run python scripts/score_jobs.py jobs/<batch-dir> --format json
```

替换为：

```
# 5. 运行单个任务（Agent 评测 + checkpoint 判分，产物写入 tasks/oncology-v2/<case_id>/runs/<时间戳>/）
uv run python -m eval.runner --task-dir tasks/oncology-v2/<case_id>

# 6. 本地轨迹浏览（一条命令启动，浏览器打开 http://127.0.0.1:8765）
uv run python -m viewer
```

（`eval/runner.py` 即评测闭环 v1 的运行器，本任务只把 README 从旧的 `run_task.py`/`jobs/` 入口切到现行入口；reader 本身在 Task 2-5 尚未就绪，README 里的 viewer 入口行会在 Task 6 再次核对实际命令。）

- [ ] **Step 7: 修改 `docs/physicianbench-study/README.md`（旧研究文档，标 legacy）**

① 表格「源码映射」中 3 行的引用改为现行入口或 legacy 标注：

```
| 单任务生命周期、Docker、评测 | `scripts/run_task.py` |
| 批量运行 | `scripts/run_batch_task.sh` |
| 结果汇总：pass@1、pass@3、pass^3、tool calls | `scripts/score_jobs.py` |
```
改成：
```
| 单任务生命周期、评测（legacy：v1 已删，现为 eval/runner.py） | `scripts/run_task.py`（已删） |
| 批量运行（legacy：v1 已删，无现行对应） | `scripts/run_batch_task.sh`（已删） |
| 结果汇总 / 轨迹浏览（现为 viewer，`uv run python -m viewer`） | `scripts/score_jobs.py`（已删） |
```

② 同一表格中「任务元数据与分类」行引用了将被删除的 `scripts/task_taxonomy_v1.json`，去掉该引用：

```
| 任务元数据与分类 | `tasks/v1/*/task.toml`、`scripts/task_taxonomy_v1.json` |
```
改成：
```
| 任务元数据与分类 | `tasks/v1/*/task.toml` |
```

③ 正文 `第 5 节` 第 5 条「有 Docker 后先只跑一个任务，再跑小批量；最后用 `scripts/score_jobs.py` 汇总。」——把结尾改为「…再跑小批量。结果查看用现行入口 `uv run python -m viewer`。」（本仓库的 v2 评测闭环入口见 `eval/runner.py`。）

④ 正文 `第 7 节` 第 3 行 `uv run python scripts/run_task.py tasks/v1/aortic_aneurysm_cad ...` 属于 v1 legacy 命令——在命令前加一行注释 `# legacy：v1 单任务 runner 已删，仅作历史记录`。

- [ ] **Step 8: 断言无残留引用**

```bash
rg -n "job_manager|score_jobs|run_batch_task|run_task" --glob '!.venv' --glob '!docs/superpowers/plans' --glob '!uv.lock' || echo "NO RESIDUAL"
```
预期：无输出（`|| echo` 打印 NO RESIDUAL）。

> 注意：`scripts/run_eval.py`、`script generate_*.py` 保留不动；`docs/physicianbench-study/README.md` 里经过 Step 7 处理后不再命中 `run_task.py`/`score_jobs.py`（run_task 字样可出现在已加 legacy 注释的行，若仍命中，确认该行属于历史说明即可接受）。

- [ ] **Step 9: 全量回归测试**

```bash
uv run pytest -q
```
预期:全部通过（删除的是旧测试，其余 124 个测试不依赖被删文件）。

- [ ] **Step 10: 更新 README 测试数量**

运行上一步后看 `uv run pytest -q` 输出的测试总数（删 2 个旧测试后约 124，Task 3/4 还会新增）。把 README「测试」节的 `uv run pytest            # 126 个单元测试：…` 里的数字改为当前实际值。

- [ ] **Step 11: 提交**

```bash
git add -A
git commit -m "chore: 移除已死的 jobs/ 约定死代码（job_manager/score_jobs/run_batch/run_task 与关联测试），README/研究文档切换为 eval/runner 与 viewer 入口"
```

---

### Task 2: 添加依赖 + 包骨架（`viewer/__init__.py`、`__main__.py`）

**Files:**
- Modify: `pyproject.toml`、`uv.lock`（由 `uv add` 自动更新）
- Create: `viewer/__init__.py`、`viewer/__main__.py`

**Interfaces:**
- Consumes: 无。
- Produces: `import viewer` 可用；`uv run python -m viewer` 能启动（依赖 `viewer.server.app`，server 在 Task 4 才落地，故本任务 __main__ 先以 stub 方式验证依赖安装）。

- [ ] **Step 1: 添加依赖**

```bash
uv add fastapi uvicorn markdown
```
预期:`pyproject.toml` 的 `dependencies` 增加 fastapi/uvicorn/markdown，`uv.lock` 更新（Task 1 Step 1 刻意未提交的 `uv.lock` 改动在此随依赖更新一并纳入）。httpx 无需显式添加（openai 已传递引入，`tests/test_viewer_server.py` 的 TestClient 依赖它）。

- [ ] **Step 2: 创建 `viewer/__init__.py`**

```python
"""OncoBench 本地轨迹浏览服务."""
```
另需确保 `viewer` 目录存在于仓库根（`mkdir viewer`）。

- [ ] **Step 3: 创建 `viewer/__main__.py`**

```python
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
```
> 本步骤先写入文件；`viewer/server.py` 尚未创建，`python -m viewer` 此刻会 `ModuleNotFoundError`——这是预期，Task 4 完成 server.py 后此入口才可用。

- [ ] **Step 4: 验证依赖可导入**

```bash
.venv/bin/python -c "import fastapi, uvicorn, markdown; print('deps OK')"
```
预期:`deps OK`。

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml uv.lock viewer/
git commit -m "chore: 添加 fastapi/uvicorn/markdown 依赖；新建 viewer 包骨架与 __main__ 入口"
```

---

### Task 3: `viewer/scanner.py` 纯函数扫描层 + 单测（G3 数据层）

**Files:**
- Create: `viewer/scanner.py`
- Test: `tests/test_viewer_scanner.py`

**Interfaces:**
- Consumes: 无。
- Produces（后续 server.py 与前端依赖的精确签名/字段名）:
  - `scanner.scan_tasks(root: Path) -> list[TaskInfo]`
  - `scanner.load_task(root: Path, case_id: str) -> TaskDetail`
  - `scanner.load_run(root: Path, case_id: str, run_id: str) -> RunDetail`
  - dataclass 字段（`asdict` 后即前端 JSON 键名）：
    - `TaskInfo`: `case_id, task_type, task_label, target_date, run_count, best_score, recent_passed, recent_total`
    - `TaskDetail`: `case_id, task_type, task_label, target_date, instruction_md, instruction_html, checkpoints, has_ground_truth, has_cleaned_csv, runs`
    - `RunSummary`: `run_id, agent_model, tool_calls, pass_count, total_count, score, status, duration_seconds, start_time`
    - `RunDetail`: `case_id, run_id, has_scorecard, scorecard, checkpoints, checkpoint_summary, agent_model, tool_calls, status, duration_seconds, start_time, events, failed_lines, report_md, report_html, ground_truth, cleaned_csv_html`
  - status 取值:`"complete" | "incomplete"`（scorecard 缺失即 incomplete）。

- [ ] **Step 1: 写失败测试**

`tests/test_viewer_scanner.py`:

```python
"""viewer.scanner 纯函数单测：tmp_path 构造假任务树。

覆盖:正常 run、缺 scorecard 的 run、坏 JSONL 行、无 run 的 case。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from viewer import scanner  # noqa: E402


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _task_toml(case_id: str, label: str, ttype: str) -> str:
    return (
        f'case_id = "{case_id}"\n'
        f'task_type = "{ttype}"\n'
        f'task_label = "{label}"\n'
        f'target_date = "2023-08-14"\n'
        f'deliverable = "output/diagnosis_report.md"\n'
        f'data_file = "cleaned_trajectory.csv"\n'
    )


def _make_tree(root: Path) -> Path:
    """构造 2 个 case：caseAAA(两个 run)+caseBBB(无 run)。"""
    c1 = root / "caseAAA"
    _write(c1 / "task.toml", _task_toml("caseAAA", "疗效评估", "T2_response"))
    _write(c1 / "instruction.md", "# 请你判断疗效\n\n正文")
    _write(c1 / "checkpoints.json", json.dumps(
        {"checkpoints": [{"checkpoint_id": "c1", "layer": "data_retrieval", "description": "查询影像",
                          "eval_method": "llm_judge", "params": {}}]}, ensure_ascii=False))
    _write(c1 / "ground_truth.json", json.dumps({"response": "PR"}, ensure_ascii=False))
    _write(c1 / "cleaned_trajectory.csv", "col1,col2\nv1,v2\n")

    # 完整 run（含一条坏 JSONL 行，应被跳过）
    r1 = c1 / "runs" / "20260101-000000"
    _write(r1 / "scorecard.json", json.dumps({
        "agent_model": "m1", "tool_calls": 3,
        "checkpoint_summary": {"total": 2, "pass": 2, "fail": 0, "score": 1.0},
        "checkpoints": [{"checkpoint_id": "c1", "layer": "x", "verdict": "pass", "judge": "code", "comment": "ok"}],
    }, ensure_ascii=False))
    _write(r1 / "trajectory.json",
        '{"type": "instruction", "timestamp": "2026-01-01T00:00:00"}\n'
        '{"type": "tool_call", "timestamp": "2026-01-01T00:00:02", "metadata": {"tool_name": "query_imaging"}}\n'
        'THIS-IS-NOT-JSON\n'
        '{"type": "final_result", "timestamp": "2026-01-01T00:00:05"}\n')
    _write(r1 / "output" / "diagnosis_report.md", "# 报告标题\n\n正文段落")

    # 缺 scorecard 的 run（模拟中断/崩溃）
    r2 = c1 / "runs" / "20260102-000000"
    _write(r2 / "trajectory.json",
        '{"type": "instruction", "timestamp": "2026-01-02T00:00:00"}\n'
        '{"type": "tool_call", "timestamp": "2026-01-02T00:00:01", "metadata": {"tool_name": "x"}}\n'
        '{"type": "final_result", "timestamp": "2026-01-02T00:00:03"}\n')

    # 无 run 的 case
    c2 = root / "caseBBB"
    _write(c2 / "task.toml", _task_toml("caseBBB", "分期", "T1_staging"))
    return root
```

```python
def test_scan_tasks(tmp_path):
    _make_tree(tmp_path)
    tasks = scanner.scan_tasks(tmp_path)
    by_id = {t.case_id: t for t in tasks}
    assert set(by_id) == {"caseAAA", "caseBBB"}
    a = by_id["caseAAA"]
    assert a.task_label == "疗效评估"
    assert a.task_type == "T2_response"
    assert a.target_date == "2023-08-14"
    assert a.run_count == 2
    assert a.best_score == 1.0
    b = by_id["caseBBB"]
    assert b.run_count == 0
    assert b.best_score is None


def test_load_task(tmp_path):
    _make_tree(tmp_path)
    det = scanner.load_task(tmp_path, "caseAAA")
    assert det.task_label == "疗效评估"
    assert "疗效" in det.instruction_md
    assert "<h1>" in det.instruction_html
    assert det.checkpoints[0]["checkpoint_id"] == "c1"
    assert len(det.runs) == 2
    assert det.has_ground_truth is True
    assert det.has_cleaned_csv is True


def test_load_run_complete(tmp_path):
    _make_tree(tmp_path)
    rd = scanner.load_run(tmp_path, "caseAAA", "20260101-000000")
    assert rd.has_scorecard is True
    assert rd.status == "complete"
    assert rd.agent_model == "m1"
    assert rd.tool_calls == 3
    assert rd.checkpoint_summary["pass"] == 2
    assert rd.duration_seconds == 5.0
    assert len(rd.events) == 3
    assert rd.failed_lines == 1
    assert rd.events[0]["type"] == "instruction"
    assert "<h1>" in rd.report_html
    assert rd.ground_truth == {"response": "PR"}
    assert "<table>" in rd.cleaned_csv_html


def test_load_run_incomplete(tmp_path):
    _make_tree(tmp_path)
    rd = scanner.load_run(tmp_path, "caseAAA", "20260102-000000")
    assert rd.has_scorecard is False
    assert rd.status == "incomplete"
    assert rd.scorecard is None
    assert rd.agent_model is None
    assert rd.tool_calls is None
    assert len(rd.events) == 3
    assert rd.duration_seconds == 3.0


def test_load_run_missing_dir_returns_empty(tmp_path):
    _make_tree(tmp_path)
    rd = scanner.load_run(tmp_path, "caseBBB", "nonexistent")
    assert rd.events == []
    assert rd.has_scorecard is False
    assert rd.report_html == ""
    assert rd.cleaned_csv_html == ""


def test_run_summaries_sorted(tmp_path):
    _make_tree(tmp_path)
    det = scanner.load_task(tmp_path, "caseAAA")
    assert [r.run_id for r in det.runs] == ["20260101-000000", "20260102-000000"]
    assert det.runs[0].status == "complete"
    assert det.runs[1].status == "incomplete"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_viewer_scanner.py -q
```
预期:FAIL（`ModuleNotFoundError: No module named 'viewer'` 或 `No module named 'scanner'`——scanner 尚未创建）。

- [ ] **Step 3: 写实现 `viewer/scanner.py`**

```python
"""OncoBench 轨迹浏览 纯函数扫描层：目录 → 结构化数据模型。

只读 `tasks/oncology-v2/<case_id>/...` 产物，不依赖 FastAPI，可纯函数单测。
每次调用现读文件、无缓存（手动刷新语义由此保证）。
spec: 2026-08-21-trajectory-viewer-design.md §4.2
"""
from __future__ import annotations

import csv
import json
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path

import markdown as _md

_MD = _md.Markdown(extensions=["fenced_code"])


# ---------------------------------------------------------------- 数据模型
@dataclass
class TaskInfo:
    case_id: str
    task_type: str = ""
    task_label: str = ""
    target_date: str = ""
    run_count: int = 0
    best_score: float | None = None
    recent_passed: int | None = None
    recent_total: int | None = None


@dataclass
class RunSummary:
    run_id: str
    agent_model: str | None = None
    tool_calls: int | None = None
    pass_count: int | None = None
    total_count: int | None = None
    score: float | None = None
    status: str = "complete"
    duration_seconds: float | None = None
    start_time: str | None = None


@dataclass
class TaskDetail:
    case_id: str
    task_type: str = ""
    task_label: str = ""
    target_date: str = ""
    instruction_md: str = ""
    instruction_html: str = ""
    checkpoints: list[dict] = field(default_factory=list)
    has_ground_truth: bool = False
    has_cleaned_csv: bool = False
    runs: list[RunSummary] = field(default_factory=list)


@dataclass
class RunDetail:
    case_id: str
    run_id: str
    has_scorecard: bool = False
    scorecard: dict | None = None
    checkpoints: list[dict] = field(default_factory=list)
    checkpoint_summary: dict | None = None
    agent_model: str | None = None
    tool_calls: int | None = None
    status: str = "incomplete"
    duration_seconds: float | None = None
    start_time: str | None = None
    events: list[dict] = field(default_factory=list)
    failed_lines: int = 0
    report_md: str = ""
    report_html: str = ""
    ground_truth: dict | None = None
    cleaned_csv_html: str = ""


# ---------------------------------------------------------------- 内部工具
def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _render_md(text: str) -> str:
    return _MD.convert(text) if text else ""


def _csv_to_table(path: Path) -> str:
    if not path.exists():
        return ""
    with open(path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return "<p>（空文件）</p>"
    thead = "<tr>" + "".join(f"<th>{escape(h)}</th>" for h in rows[0]) + "</tr>"
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>"
        for row in rows[1:]
    )
    return (f"<div class='table-wrap'><table><thead>{thead}</thead>"
            f"<tbody>{body}</tbody></table></div>")


def _parse_trajectory(path: Path) -> tuple[list[dict], int]:
    """逐行 json.loads；坏行跳过并计数。"""
    events: list[dict] = []
    failed = 0
    for line in _read_text(path).splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            failed += 1
    return events, failed


def _first_timestamp(events: list[dict]) -> str | None:
    for ev in events:
        ts = ev.get("timestamp")
        if ts:
            return ts
    return None


def _duration_seconds(first: str | None, last: str | None) -> float | None:
    if not first or not last:
        return None
    try:
        return (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds()
    except (ValueError, TypeError):
        return None


def _read_report(run_dir: Path) -> tuple[str, str]:
    """取 output/ 下第一个 .md 作为交付报告：返回(原文, HTML)。"""
    out_dir = run_dir / "output"
    md_files = sorted(out_dir.glob("*.md")) if out_dir.is_dir() else []
    if not md_files:
        return "", ""
    text = md_files[0].read_text(encoding="utf-8")
    return text, _render_md(text)


# ---------------------------------------------------------------- run
def load_run(root: Path, case_id: str, run_id: str) -> RunDetail:
    """读单个 run：scorecard + trajectory 事件 + 报告 + 病例 ground_truth + CSV 表。"""
    case_dir = root / case_id
    run_dir = case_dir / "runs" / run_id
    sc = _read_json(run_dir / "scorecard.json")
    checkpoints: list[dict] = []
    checkpoint_summary = None
    if sc is not None:
        checkpoints = sc.get("checkpoints", []) or []
        checkpoint_summary = sc.get("checkpoint_summary")
    events, failed = _parse_trajectory(run_dir / "trajectory.json")
    first = _first_timestamp(events)
    last = events[-1].get("timestamp") if events else None
    duration = _duration_seconds(first, last)
    report_md, report_html = _read_report(run_dir)
    return RunDetail(
        case_id=case_id,
        run_id=run_id,
        has_scorecard=sc is not None,
        scorecard=sc,
        checkpoints=checkpoints,
        checkpoint_summary=checkpoint_summary,
        agent_model=sc.get("agent_model") if sc else None,
        tool_calls=sc.get("tool_calls") if sc else None,
        status="complete" if sc is not None else "incomplete",
        duration_seconds=duration,
        start_time=first,
        events=events,
        failed_lines=failed,
        report_md=report_md,
        report_html=report_html,
        ground_truth=_read_json(case_dir / "ground_truth.json"),
        cleaned_csv_html=_csv_to_table(case_dir / "cleaned_trajectory.csv"),
    )


# ---------------------------------------------------------------- task
def _list_runs(runs_dir: Path) -> list[RunSummary]:
    if not runs_dir.is_dir():
        return []
    out = []
    for d in sorted(runs_dir.glob("*")):
        if not d.is_dir():
            continue
        sc = _read_json(d / "scorecard.json")
        s = RunSummary(run_id=d.name)
        if sc is not None:
            s.agent_model = sc.get("agent_model")
            s.tool_calls = sc.get("tool_calls")
            cs = sc.get("checkpoint_summary") or {}
            s.pass_count = cs.get("pass")
            s.total_count = cs.get("total")
            s.score = cs.get("score")
        else:
            s.status = "incomplete"
        events, _ = _parse_trajectory(d / "trajectory.json")
        first = _first_timestamp(events)
        last = events[-1].get("timestamp") if events else None
        s.start_time = first
        s.duration_seconds = _duration_seconds(first, last)
        out.append(s)
    return out


def load_task(root: Path, case_id: str) -> TaskDetail:
    case_dir = root / case_id
    meta = tomllib.loads((case_dir / "task.toml").read_text(encoding="utf-8"))
    instruction_raw = _read_text(case_dir / "instruction.md")
    checkpoints = (_read_json(case_dir / "checkpoints.json") or {}).get("checkpoints", []) or []
    return TaskDetail(
        case_id=case_id,
        task_type=meta.get("task_type", ""),
        task_label=meta.get("task_label", ""),
        target_date=meta.get("target_date", ""),
        instruction_md=instruction_raw,
        instruction_html=_render_md(instruction_raw),
        checkpoints=checkpoints,
        has_ground_truth=(case_dir / "ground_truth.json").exists(),
        has_cleaned_csv=(case_dir / "cleaned_trajectory.csv").exists(),
        runs=_list_runs(case_dir / "runs"),
    )


# ---------------------------------------------------------------- 顶层扫描
def _scan_task(case_dir: Path) -> TaskInfo | None:
    try:
        meta = tomllib.loads((case_dir / "task.toml").read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return None
    runs = _list_runs(case_dir / "runs")
    best = None
    recent_passed = recent_total = None
    if runs:
        for rs in runs:
            if rs.score is not None:
                best = rs.score if best is None else max(best, rs.score)
        recent_passed, recent_total = runs[-1].pass_count, runs[-1].total_count
    return TaskInfo(
        case_id=meta.get("case_id", case_dir.name),
        task_type=meta.get("task_type", ""),
        task_label=meta.get("task_label", ""),
        target_date=meta.get("target_date", ""),
        run_count=len(runs),
        best_score=best,
        recent_passed=recent_passed,
        recent_total=recent_total,
    )


def scan_tasks(root: Path) -> list[TaskInfo]:
    """遍历 `root/*/`，读 task.toml + 统计 runs，返回病例列表。"""
    out: list[TaskInfo] = []
    for case_dir in sorted(d for d in root.glob("*") if d.is_dir()):
        info = _scan_task(case_dir)
        if info is not None:
            out.append(info)
    return out
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_viewer_scanner.py -q
```
预期:6 个测试全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add viewer/scanner.py tests/test_viewer_scanner.py
git commit -m "feat: viewer scanner 纯函数扫描层（scan/load task/run）+ 单测"
```

---

### Task 4: `viewer/server.py` FastAPI（3 个 API）+ API 测试（G2 / G3 服务层）

**Files:**
- Create: `viewer/server.py`
- Test: `tests/test_viewer_server.py`

**Interfaces:**
- Consumes: `viewer.scanner` 的三个函数与 dataclass（`asdict`）。
- Produces:
  - `create_app(root: Path | None = None) -> FastAPI`
  - `server.DEFAULT_ROOT: Path`
  - 模块级 `app: FastAPI = create_app()`
  - REST 契约：`GET /api/tasks` → `list[TaskInfo]`；`GET /api/tasks/{case_id}` → `TaskDetail`；`GET /api/tasks/{case_id}/runs/{run_id}` → `RunDetail`；未知 case/run → 404 + JSON 错误体。

- [ ] **Step 1: 写失败测试**

`tests/test_viewer_server.py`:

```python
"""viewer.server FastAPI API 测试：3 个 API 成功路径 + 404。

用 tmp_path 构造假任务树（与 scanner 测试同一套，这里内联复刻）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from viewer.server import create_app  # noqa: E402


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_tree(root: Path) -> Path:
    c1 = root / "caseAAA"
    _write(c1 / "task.toml",
        'case_id = "caseAAA"\ntask_type = "T2_response"\ntask_label = "疗效评估"\n'
        'target_date = "2023-08-14"\ndeliverable = "output/diagnosis_report.md"\n'
        'data_file = "cleaned_trajectory.csv"\n')
    _write(c1 / "instruction.md", "# 请你判断疗效\n\n正文")
    _write(c1 / "checkpoints.json", json.dumps(
        {"checkpoints": [{"checkpoint_id": "c1"}]}, ensure_ascii=False))
    _write(c1 / "ground_truth.json", json.dumps({"response": "PR"}, ensure_ascii=False))
    _write(c1 / "cleaned_trajectory.csv", "col1,col2\nv1,v2\n")
    r1 = c1 / "runs" / "20260101-000000"
    _write(r1 / "scorecard.json", json.dumps({
        "agent_model": "m1", "tool_calls": 3,
        "checkpoint_summary": {"total": 2, "pass": 2, "score": 1.0},
        "checkpoints": [{"checkpoint_id": "c1", "verdict": "pass"}],
    }, ensure_ascii=False))
    _write(r1 / "trajectory.json",
        '{"type": "instruction", "timestamp": "2026-01-01T00:00:00"}\n'
        'BAD\n'
        '{"type": "final_result", "timestamp": "2026-01-01T00:00:05"}\n')
    _write(r1 / "output" / "diagnosis_report.md", "# 报告标题\n\n正文")
    c2 = root / "caseBBB"
    _write(c2 / "task.toml",
        'case_id = "caseBBB"\ntask_type = "T1_staging"\ntask_label = "分期"\n'
        'target_date = "2023-08-14"\ndeliverable = "output/diagnosis_report.md"\n'
        'data_file = "cleaned_trajectory.csv"\n')
    return root


@pytest.fixture()
def client(tmp_path):
    _make_tree(tmp_path)
    return TestClient(create_app(root=tmp_path))


def test_list_tasks(client):
    r = client.get("/api/tasks")
    assert r.status_code == 200
    body = r.json()
    ids = {t["case_id"] for t in body}
    assert ids == {"caseAAA", "caseBBB"}
    a = next(t for t in body if t["case_id"] == "caseAAA")
    assert a["run_count"] == 1
    assert a["best_score"] == 1.0


def test_task_detail(client):
    r = client.get("/api/tasks/caseAAA")
    assert r.status_code == 200
    body = r.json()
    assert body["case_id"] == "caseAAA"
    assert body["instruction_md"] != ""
    assert len(body["runs"]) == 1
    assert body["runs"][0]["run_id"] == "20260101-000000"
    assert body["has_ground_truth"] is True


def test_run_detail(client):
    r = client.get("/api/tasks/caseAAA/runs/20260101-000000")
    assert r.status_code == 200
    body = r.json()
    assert body["tool_calls"] == 3
    assert len(body["events"]) == 2
    assert body["failed_lines"] == 1
    assert "<table>" in body["cleaned_csv_html"]
    assert body["ground_truth"] == {"response": "PR"}


def test_unknown_case_404(client):
    r = client.get("/api/tasks/nope")
    assert r.status_code == 404
    assert r.json()["detail"]


def test_unknown_run_404(client):
    r = client.get("/api/tasks/caseAAA/runs/nope")
    assert r.status_code == 404
    assert r.json()["detail"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_viewer_server.py -q
```
预期:FAIL（`No module named 'viewer.server'`）。

- [ ] **Step 3: 写实现 `viewer/server.py`**

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_viewer_server.py -q
```
预期:5 个测试全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add viewer/server.py tests/test_viewer_server.py
git commit -m "feat: viewer FastAPI 服务（/api/tasks 三端点 + 404）+ API 测试"
```

---

### Task 5: 前端静态单页（index.html / app.js / style.css）（G3 前端 / G4 手动刷新）

**Files:**
- Create: `viewer/static/index.html`、`viewer/static/app.js`、`viewer/static/style.css`

**Interfaces:**
- Consumes: Task 3/4 的 JSON 键名（`TaskInfo`/`TaskDetail`/`RunDetail` 经 `asdict` 序列化）。
- Produces: 可直接 jsDelivr 无依赖的静态页；`GET /` 经 FastAPI 静态挂载返回 index.html（`html=True`）。

**验收数据（真实，spec §6）：** `tasks/oncology-v2` 下有 2 个 case（`00151e6a…`、`00813296…`），共 3 个 run。选中 `00151e6a…` 的 `20260820-210036` run，应看到 `qwen3.8`、`6/6` 全 pass、11 次工具调用、轨迹时间线含每条 tool_call 入参/返回、报告渲染出 PR 结论。

- [ ] **Step 1: 创建 `viewer/static/index.html`**

```html
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OncoBench 轨迹浏览器</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div id="app">
    <aside id="sidebar">
      <div class="sidebar-head">
        <h1>轨迹浏览器</h1>
        <button id="refresh-btn" title="重新读取当前视图">⟳ 刷新</button>
      </div>
      <div id="task-list"></div>
      <div id="sidebar-empty" class="empty hidden">暂无任务目录</div>
    </aside>
    <main id="main">
      <div id="overview"></div>
      <div id="run-select" class="hidden"></div>
      <div id="tab-bar"></div>
      <div id="tab-content"><div class="empty">← 从左侧选择一个病例</div></div>
    </main>
  </div>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 创建 `viewer/static/app.js`**

```javascript
// OncoBench 轨迹浏览器 前端逻辑（零构建，原生 JS）
// spec: 2026-08-21-trajectory-viewer-design.md §4.2 前端
'use strict';

const state = { caseId: null, runId: null, task: null, run: null, activeTab: 'checkpoints' };
const $ = (id) => document.getElementById(id);

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} ${url}`);
  return r.json();
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function badgeClass(pass, total) {
  if (total == null || total === 0) return 'badge-empty';
  if (pass === total) return 'badge-good';
  if (pass === 0) return 'badge-bad';
  return 'badge-warn';
}

// -------------------- 侧边栏 --------------------
async function loadTasks() {
  const tasks = await fetchJSON('/api/tasks');
  const list = $('task-list');
  list.innerHTML = '';
  $('sidebar-empty').classList.toggle('hidden', tasks.length > 0);
  tasks.forEach(t => {
    const btn = document.createElement('button');
    btn.className = 'task-item' + (t.case_id === state.caseId ? ' active' : '');
    btn.innerHTML = `
      <span class="task-id">${esc(t.case_id.slice(0, 8))}</span>
      <span class="task-label">${esc(t.task_label || '')}</span>
      <span class="badge ${badgeClass(t.recent_passed, t.recent_total)}">
        ${t.recent_passed ?? '—'}/${t.recent_total ?? '—'} · ${t.run_count} run</span>`;
    btn.onclick = () => selectCase(t.case_id);
    list.appendChild(btn);
  });
}

// -------------------- 概览 + run 选择 --------------------
function overviewHTML(t) {
  const run = (t.runs || []).find(r => r.run_id === state.runId) || null;
  return `
    <div class="overview">
      <div class="ov-title">${esc(t.task_label || t.case_id)}
        <span class="mono">${esc(t.case_id.slice(0, 8))}</span></div>
      <div class="ov-grid">
        <div><label>task_type</label><span>${esc(t.task_type || '—')}</span></div>
        <div><label>target_date</label><span>${esc(t.target_date || '—')}</span></div>
        <div><label>模型</label><span>${run ? esc(run.agent_model ?? '—') : '—'}</span></div>
        <div><label>run 时间</label><span class="mono">${run ? esc(run.run_id) : '—'}</span></div>
        <div><label>总得分</label><span>${run && run.pass_count != null ? esc(run.pass_count) + '/' + esc(run.total_count) : '未完成'}</span></div>
        <div><label>工具调用</label><span>${run ? esc(run.tool_calls ?? '—') : '—'}</span></div>
        <div><label>耗时</label><span>${run && run.duration_seconds != null ? run.duration_seconds.toFixed(1) + 's' : '—'}</span></div>
        <div><label>状态</label><span>${run ? esc(run.status) : '—'}</span></div>
      </div>
      <details class="instruction"><summary>Instruction（题干全文）</summary>
        <div class="md">${t.instruction_html || esc(t.instruction_md)}</div>
      </details>
    </div>`;
}

function renderRunSelector(runs) {
  const sel = $('run-select');
  sel.innerHTML = '';
  sel.classList.toggle('hidden', runs.length === 0);
  runs.forEach(r => {
    const chip = document.createElement('button');
    chip.className = 'run-chip' + (r.run_id === state.runId ? ' active' : '');
    const score = r.pass_count != null ? `${r.pass_count}/${r.total_count}` : '未完成';
    chip.textContent = `${r.run_id} · ${r.agent_model || '—'} · ${score}`;
    chip.onclick = () => selectRun(state.caseId, r.run_id);
    sel.appendChild(chip);
  });
}

// -------------------- 标签页 --------------------
const TABS = [
  ['checkpoints', 'Checkpoint 情况'],
  ['trajectory', '完整轨迹'],
  ['report', '交付物'],
  ['groundtruth', '标准答案'],
  ['csv', '病例数据'],
];

function renderTabs() {
  const bar = $('tab-bar');
  bar.innerHTML = '';
  TABS.forEach(([key, label]) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.className = key === state.activeTab ? 'tab active' : 'tab';
    b.onclick = () => { state.activeTab = key; renderTabs(); renderActiveTab(); };
    bar.appendChild(b);
  });
}

function renderActiveTab() {
  const run = state.run;
  const sec = $('tab-content');
  switch (state.activeTab) {
    case 'checkpoints': sec.innerHTML = checkpointsHTML(run); break;
    case 'trajectory': sec.innerHTML = trajectoryHTML(run); break;
    case 'report': sec.innerHTML = reportHTML(run); break;
    case 'groundtruth': sec.innerHTML = groundTruthHTML(run); break;
    case 'csv': sec.innerHTML = csvHTML(run); break;
  }
}

function checkpointsHTML(run) {
  const cps = (run && run.checkpoints) || [];
  if (!cps.length) return '<div class="empty">该 run 无 checkpoint 记录（可能未完成判分）。</div>';
  return `<div class="table-wrap"><table><thead><tr>
      <th>checkpoint_id</th><th>layer</th><th>description</th><th>verdict</th><th>judge</th><th>comment</th>
    </tr></thead><tbody>${cps.map(c => `
      <tr>
        <td class="mono">${esc(c.checkpoint_id)}</td>
        <td>${esc(c.layer)}</td>
        <td>${esc(c.description)}</td>
        <td><span class="verdict ${esc(c.verdict)}">${esc(c.verdict)}</span></td>
        <td>${esc(c.judge)}</td>
        <td>${esc(c.comment)}</td>
      </tr>`).join('')}</tbody></table></div>`;
}

function eventCard(cls, title, ev) {
  return `<div class="card ${cls}"><div class="card-head">${title}</div><pre>${esc(ev.content)}</pre></div>`;
}

function trajectoryHTML(run) {
  if (!run || !run.events.length) return '<div class="empty">该 run 无轨迹事件。</div>';
  let step = 0;
  const html = run.events.map(ev => {
    switch (ev.type) {
      case 'instruction':
        return eventCard('instruction', 'Instruction', ev);
      case 'agent_initialized': {
        const m = ev.metadata || {};
        return eventCard('init', `Agent 初始化: ${esc(m.model || '')}`, ev);
      }
      case 'llm_response': {
        step += 1;
        const m = ev.metadata || {};
        const tokens = m.completion_tokens != null ? `${m.prompt_tokens || 0}→${m.completion_tokens}` : '';
        const reasoning = (m.raw_message && m.raw_message.reasoning) || null;
        return `
          <div class="card llm">
            <div class="card-head">LLM 回复 <span class="chip">step ${step}</span>
              ${tokens ? `<span class="tokens">${esc(tokens)} tokens</span>` : ''}
              ${m.finish_reason ? `<span class="mono">${esc(m.finish_reason)}</span>` : ''}</div>
            ${reasoning ? `<details class="reasoning"><summary>reasoning</summary><pre>${esc(reasoning)}</pre></details>` : ''}
            <details class="llm-body" open><summary>正文（可折叠）</summary><pre>${esc(ev.content)}</pre></details>
          </div>`;
      }
      case 'tool_call': {
        const m = ev.metadata || {};
        const input = m.input ? JSON.stringify(m.input, null, 2) : '';
        const output = String(m.output ?? '');
        const truncated = output.length > 800;
        return `
          <div class="card tool">
            <div class="card-head">🔧 ${esc(m.tool_name || 'tool')}</div>
            ${input ? `<pre class="input">入参: ${esc(input)}</pre>` : ''}
            <details class="output">
              <summary>返回内容${truncated ? `（截断，全长 ${output.length} 字符）` : ''}</summary>
              <pre>${esc(truncated ? output.slice(0, 800) : output)}${truncated ? '…' : ''}</pre>
              ${truncated ? `<details class="full"><summary>展开完整</summary><pre>${esc(output)}</pre></details>` : ''}
            </details>
          </div>`;
      }
      case 'final_result':
        return `<div class="card final"><div class="card-head">Final Result</div><pre>${esc(ev.content)}</pre></div>`;
      default:
        return `<div class="card other"><div class="card-head">${esc(ev.type)}</div><pre>${esc(JSON.stringify(ev, null, 2))}</pre></div>`;
    }
  }).join('');
  const warn = run.failed_lines > 0 ? `<div class="warn">⚠️ ${run.failed_lines} 行轨迹解析失败（已跳过）</div>` : '';
  return warn + html;
}

function reportHTML(run) {
  if (!run || !run.report_html) return '<div class="empty">该 run 无可交付报告（output/*.md 缺失）。</div>';
  return `<div class="md report">${run.report_html}</div>`;
}

function groundTruthHTML(run) {
  if (!run || run.ground_truth == null) return '<div class="empty">该病例缺少 ground_truth.json。</div>';
  return `<pre class="json">${esc(JSON.stringify(run.ground_truth, null, 2))}</pre>`;
}

function csvHTML(run) {
  if (!run || !run.cleaned_csv_html) return '<div class="empty">该病例缺少 cleaned_trajectory.csv。</div>';
  return run.cleaned_csv_html;
}

// -------------------- 流程 --------------------
async function selectRun(caseId, runId) {
  state.runId = runId;
  state.run = await fetchJSON(`/api/tasks/${caseId}/runs/${runId}`);
  $('overview').innerHTML = overviewHTML(state.task);
  renderRunSelector((state.task && state.task.runs) || []);
  renderTabs();
  renderActiveTab();
}

async function selectCase(caseId) {
  state.caseId = caseId;
  state.runId = null;
  state.run = null;
  await loadTasks(); // 更新侧边栏 active 高亮
  const task = await fetchJSON(`/api/tasks/${caseId}`);
  state.task = task;
  if (!task.runs.length) {
    $('overview').innerHTML = overviewHTML(task);
    renderRunSelector([]);
    $('tab-bar').innerHTML = '';
    $('tab-content').innerHTML = '<div class="empty">该病例暂无 run。运行评测后产物会出现在 runs/ 下。</div>';
    return;
  }
  await selectRun(caseId, task.runs[0].run_id);
}

async function refresh() {
  await loadTasks();
  if (!state.caseId) return;
  const task = await fetchJSON(`/api/tasks/${state.caseId}`);
  state.task = task;
  if (state.runId) await selectRun(state.caseId, state.runId);
  else if (task.runs.length) await selectRun(state.caseId, task.runs[0].run_id);
  else $('overview').innerHTML = overviewHTML(task);
}

document.addEventListener('DOMContentLoaded', () => {
  $('refresh-btn').addEventListener('click', () =>
    refresh().catch(e => { $('tab-content').innerHTML = `<div class="empty">刷新失败：${esc(e.message)}</div>`; }));
  loadTasks().catch(e => { $('sidebar-empty').textContent = '加载失败：' + e.message; });
});
```

- [ ] **Step 3: 创建 `viewer/static/style.css`**

```css
:root {
  --bg: #f5f6f8; --panel: #fff; --border: #e2e5ea; --text: #1f2328;
  --muted: #6b7280; --good: #16a34a; --warn: #d97706; --bad: #dc2626;
  --accent: #2563eb;
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       color: var(--text); background: var(--bg); }
#app { display: flex; height: 100vh; }
#sidebar { width: 280px; min-width: 280px; background: var(--panel);
           border-right: 1px solid var(--border); display: flex; flex-direction: column; }
.sidebar-head { display: flex; align-items: center; justify-content: space-between;
                padding: 12px 14px; border-bottom: 1px solid var(--border); }
.sidebar-head h1 { font-size: 15px; margin: 0; }
#refresh-btn { border: 1px solid var(--border); background: #fff; border-radius: 6px;
               padding: 6px 10px; cursor: pointer; font-size: 13px; }
#refresh-btn:hover { background: #f0f2f5; }
#task-list { overflow-y: auto; flex: 1; padding: 8px; }
.task-item { display: flex; flex-direction: column; gap: 3px; width: 100%;
             text-align: left; background: transparent; border: 1px solid transparent;
             border-radius: 8px; padding: 8px 10px; margin-bottom: 6px; cursor: pointer; }
.task-item:hover { background: #f0f2f5; }
.task-item.active { background: #e8f0fe; border-color: var(--accent); }
.task-id { font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: var(--muted); }
.task-label { font-size: 13px; font-weight: 600; }
.badge { font-size: 11px; border-radius: 10px; padding: 1px 8px; color: #fff; align-self: flex-start; }
.badge-good { background: var(--good); }
.badge-warn { background: var(--warn); }
.badge-bad { background: var(--bad); }
.badge-empty { background: var(--muted); }
#main { flex: 1; overflow: auto; padding: 18px 22px; }
.empty { color: var(--muted); padding: 20px; text-align: center; }
.hidden { display: none !important; }
.mono { font-family: ui-monospace, Menlo, monospace; }
.overview { background: var(--panel); border: 1px solid var(--border);
            border-radius: 10px; padding: 16px 18px; margin-bottom: 14px; }
.ov-title { font-size: 17px; font-weight: 700; margin-bottom: 10px; }
.ov-title .mono { font-size: 12px; color: var(--muted); font-weight: 400; }
.ov-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px 16px; }
.ov-grid div { display: flex; flex-direction: column; }
.ov-grid label { font-size: 11px; color: var(--muted); }
.ov-grid span { font-size: 13px; }
.instruction { margin-top: 12px; border-top: 1px dashed var(--border); padding-top: 10px; }
.instruction summary { cursor: pointer; font-weight: 600; font-size: 13px; }
#run-select { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.run-chip { border: 1px solid var(--border); background: var(--panel); border-radius: 16px;
            padding: 6px 12px; font-size: 12px; cursor: pointer; }
.run-chip.active { background: var(--accent); color: #fff; border-color: var(--accent); }
#tab-bar { display: flex; gap: 6px; border-bottom: 2px solid var(--border); margin-bottom: 14px; }
.tab { background: transparent; border: none; padding: 8px 14px; cursor: pointer;
       font-size: 13px; color: var(--muted); border-bottom: 2px solid transparent; margin-bottom: -2px; }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }
#tab-content { }
.table-wrap { overflow-x: auto; background: var(--panel); border: 1px solid var(--border);
              border-radius: 8px; }
table { border-collapse: collapse; width: 100%; font-size: 12px; }
th, td { border-bottom: 1px solid var(--border); padding: 6px 10px; text-align: left; vertical-align: top; }
th { background: #fafbfc; position: sticky; top: 0; }
.verdict { padding: 1px 8px; border-radius: 10px; color: #fff; font-size: 11px; }
.verdict.pass { background: var(--good); }
.verdict.fail { background: var(--bad); }
.verdict.error { background: var(--warn); }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
        padding: 10px 12px; margin-bottom: 10px; }
.card-head { font-weight: 600; font-size: 13px; margin-bottom: 6px; }
.card-head .chip { background: #e5e7eb; border-radius: 10px; font-size: 11px; padding: 0 7px; font-weight: 400; }
.card-head .tokens, .card-head .mono { color: var(--muted); font-size: 11px; margin-left: 6px; }
.card.tool { border-left: 3px solid #9333ea; }
.card.llm { border-left: 3px solid #2563eb; }
.card.final, .card.instruction { border-left: 3px solid var(--good); }
.card.init { border-left: 3px solid var(--muted); }
pre { white-space: pre-wrap; word-break: break-word; background: #fafbfc; border: 1px solid var(--border);
      border-radius: 6px; padding: 8px; font-size: 12px; margin: 6px 0 0; }
pre.json { max-height: 420px; overflow: auto; }
details.output summary, details.reasoning summary, details.full summary, details.llm-body summary {
  cursor: pointer; font-size: 12px; color: var(--muted); }
.warn { color: var(--warn); font-size: 12px; margin-bottom: 10px; }
.md { line-height: 1.7; }
.md h1, .md h2, .md h3 { margin: 14px 0 8px; }
.md table { margin: 10px 0; }
```

- [ ] **Step 4: 启动服务并人工验收七块内容 + 刷新/空状态/缺 scorecard（G4/G3）**

```bash
uv run python -m viewer
# 另开终端：
#   open http://127.0.0.1:8765
```
人工核对（spec §6 验收 2/3/4）：
- 左侧可见 2 个病例、3 个 run，徽标显示得分。
- 选中 `00151e6a…` → 默认选中 `20260820-210036` → 顶部概览显示 `qwen3.8`、`6/6`、工具调用次数、耗时、instruction 全文。
- 「Checkpoint 情况」标签：6 项全 pass（verdict=pass）。
- 「完整轨迹」标签：可见 11 次工具调用的入参与返回；`tool_call` 返回内容默认收起、可展开完整；`llm_response` 可折叠、含 token 数与 finish_reason；末尾 `final_result`。
- 「交付物」标签：报告渲染出 PR 结论。
- 「标准答案」「病例数据」标签正常显示。
- 点「刷新」按钮重拉当前视图；把某个 scorecard 临时改名（或选中缺 scorecard 的 run）观察「未完成/incomplete」标记——核对后还原。
- 空状态：临时把 `tasks/oncology-v2` 里两个 case 目录改名触发「暂无任务目录」，核对后还原（确认 server 仍读磁盘、无缓存）。

> 说明：缺 scorecard 的 run 若暂时不存在于真实数据，可临时在某 run 目录下新建空目录 `runs/__manualtest__/` 并放一个只含 trajectory.json 的文件来验证「未完成」分支，之后删除该目录（属运行期临时验证，不入库）。

- [ ] **Step 5: 提交**

```bash
git add viewer/static/
git commit -m "feat: viewer 前端静态单页（概览/checkpoint/轨迹时间线/交付物/标准答案/病例数据 + 手动刷新）"
```

---

### Task 6: README 完善 + 全量回归 + 收尾（G2 / G5 / §7）

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 2-5 的成品（`uv run python -m viewer` 可用、3 个 API 正常）。
- Produces: README 完整反映新 viewer 入口与运行方式；全量测试通过，满足验收。

- [ ] **Step 1: 在 README 快速开始的 viewer 命令下方补一段「轨迹浏览」说明**

把 Task 1 Step 6 写入的 viewer 步骤（`# 6. 本地轨迹浏览…`）下面追加使用说明（用 `edit` 在其后插入）：

```markdown
`uv run python -m viewer` 启动本地轨迹浏览服务，浏览器打开 http://127.0.0.1:8765。
功能：左侧选病例 → 选 run，右侧查看[概览 / Checkpoint 情况 / 完整轨迹时间线 / 交付物报告 / 标准答案 / 病例数据]。
数据来源为 `tasks/oncology-v2/<case_id>/runs/<时间戳>/` 真实运行产物（只读）；右上角「刷新」手动重读，无自动轮询。
支持 `VIEWER_ROOT` 环境变量指定其它任务集根目录（默认 `tasks/oncology-v2`）。
```

- [ ] **Step 2: 目录结构补充 viewer 说明（若 Task 1 已加则跳过）**

确认 README「目录结构」块已含 `viewer/` 条目（Task 1 Step 5 已加）；若缺，补上 `viewer/` 一行并注明「本地轨迹浏览服务，`uv run python -m viewer`」。

- [ ] **Step 3: 全量回归 + 测试数核对**

```bash
uv run pytest -q
```
预期:全部通过（含现有 124 个 + 新增 scanner/server 11 个），无失败。把输出中的总数与 README「测试」节数字核对一致（`uv run pytest -q` 会打印 `N passed`）。

- [ ] **Step 4: 断言无 jobs 残留（G1 验收）**

```bash
git grep -n "job_manager\|score_jobs\|run_batch_task" -- ':!*.lock' ; echo "exit=$?"
```
预期:`exit=1`（grep 无匹配）。若命中，确认所在文件属历史/文档说明或排除项（`docs/superpowers/plans` 历史记录除外），否则回到 Task 1 修。

- [ ] **Step 5: 最终人工验收启动（G2）**

```bash
uv run python -m viewer
```
预期:uvicorn 日志显示 `Uvicorn running on http://127.0.0.1:8765`；浏览器 8765 端口可访问并完成 spec §6 第 3 条核对（`00151e6a…`/`20260820-210036`：qwen3.8 / 6.0 分 / 工具调用次数 / 耗时 / 6 项全 pass / 11 次工具调用 / PR 报告）。

- [ ] **Step 6: 提交**

```bash
git add README.md
git commit -m "docs: README 补充 viewer 轨迹浏览说明与 VIEWER_ROOT 用法"
```

---

## Self-Review 对照表

| Spec 需求 | 对应 Task |
|---|---|
| G1 清除旧 jobs 约定 | Task 1（删除 7 文件 + README/trajectory/study 文档修改 + rg 断言 Step 8/9、Task 6 Step 4） |
| G2 `uv run python -m viewer` 一条命令启动 8765 | Task 2（__main__）、Task 4（server）、Task 5/6（人工验收） |
| G3 扫描 2 case/3 run，展示七块内容 | Task 3（scanner 数据层）、Task 5（前端 5 标签 + 概览 8 字段 + instruction） |
| G3 顶部概览 8 字段（含 instruction 全文） | Task 5 `overviewHTML` |
| G3 Checkpoint 表（verdict/判定方式/layer/评语） | Task 5 `checkpointsHTML`（读 scorecard.checkpoints） |
| G3 完整轨迹时间线（llm 折叠+token / tool 入参+完整返回 / final_result） | Task 5 `trajectoryHTML` |
| G3 交付物渲染 | Task 5 `reportHTML`（scanner `_read_report`→`report_html`） |
| G3 标准答案 | Task 3 `load_run`读 ground_truth + Task 5 `groundTruthHTML` |
| G3 病例数据表格 | Task 3 `_csv_to_table`→`cleaned_csv_html` + Task 5 `csvHTML` |
| G3 任务信息（checkpoints 定义） | Task 3 `load_task` checkpoints + Task 5 overview/details |
| G4 手动刷新 + 切换即重读（无轮询） | Task 5 `refresh()` + 每次 fetch；scanner 无缓存（Task 3 注释） |
| G5 scanner 层 + API 层单测 | Task 3 `tests/test_viewer_scanner.py`（6 个）、Task 4 `tests/test_viewer_server.py`（5 个） |
| Non-Goal：不改 website/、不轮询、不鉴权、不 e2e、不多任务集、不改 runner 产物 | Global Constraints 明确禁止，各 Task 未触碰 |
| §4.1 修复 agent/trajectory.py docstring | Task 1 Step 4 |
| §5 测试：缺 scorecard / 坏 JSONL / 缺失 gt/csv | Task 3 测试（incomplete / failed_lines / missing-dir） |
| §6 验收：qwen3.8/6.0/11 次调用/PR | Task 5 Step 4、Task 6 Step 5 人工核对 |
| §7 开工前先提交 main 未提交改动再开分支 | Task 1 Step 1/2 |

**类型一致性自检：** `RunDetail`/`TaskDetail`/`TaskInfo`/`RunSummary` 字段名在 Task 3 定义、Task 4 `asdict` 序列化、Task 5 前端 `r.pass_count`/`run.events`/`run.write_file` 等一律一致；`create_app` 签名在 Task 4 定义、Task 6 未改；`load_run/load_task/scan_tasks` 签名在 Task 3 定义、Task 4 仅按名调用。已确认无跨任务命名漂移。

**占位符自检：** 所有代码步骤均给出完整可运行代码，无 TBD/TODO/「类似上文」等占位；测试包含具体断言值。
