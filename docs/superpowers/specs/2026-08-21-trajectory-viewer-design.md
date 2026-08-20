# Spec: 本地轨迹浏览服务（trajectory viewer）+ 旧 jobs 约定清理

- **日期**: 2026-08-21
- **状态**: Approved（2026-08-21 用户批准）
- **分支**: 新开 `feat/trajectory-viewer`
- **上游依赖**: OncoBench 评测闭环 v1（已合入 main，产出 `tasks/oncology-v2/*/runs/` 真实运行产物）
- **范围**: ① 新增本地轨迹浏览 Web 服务（新 `viewer/` 包）② 删除旧 jobs/ 目录约定相关死代码

---

## 1. 背景与动机

评测闭环已能产出完整运行产物（trajectory JSONL + scorecard + 交付报告），但查看方式只有命令行：

```bash
uv run python scripts/score_jobs.py <jobs目录>   # 旧约定，实际产物根本不在 jobs/ 下
cat tasks/oncology-v2/<case>/runs/<ts>/scorecard.json
```

问题：

1. **轨迹是核心数据却不可见**：trajectory.json（实为 JSONL）里每轮 LLM 回复、每次工具调用的完整入参/返回，是分析"考生怎么查、怎么答、在哪翻车"的一手材料，现在只能 cat 原始文件
2. **旧 jobs/ 约定已死**：README 和脚本描述的运行产物布局是 `jobs/<batch>/<task>/`（v1 时代，`scripts/run_task.py` + `run_batch_task.sh`），但 v2 评测闭环（`eval/runner.py`）实际写到 `tasks/oncology-v2/<case>/runs/<时间戳>/`。两套约定并存造成困惑；且 v1 runner 的目标目录 `tasks/oncology-v1` 已不存在，整条链路是死代码
3. **现有 website/ 是硬编码 demo**（healthagentbench 开源展示页，数据写死在 ts 文件里），不读真实产物，本需求不动它

目标：一个**本地、零构建、一条命令启动**的 Web 服务，选病例 → 选 run → 立即看到完整轨迹、得分卡、交付物、标准答案、病例数据。

## 2. 目标

### 必须达成

- G1: 清除旧 jobs/ 约定（见 §4.1），仓库内不再存在 jobs 布局的任何实现
- G2: `uv run python -m viewer` 一条命令启动，打开 `http://127.0.0.1:8765` 可用
- G3: 扫描 `tasks/oncology-v2/*/runs/*`，列出全部病例与 run；选择后展示七块内容：
  1. 顶部概览：case_id、任务标签、task_type、target_date、**instruction 全文**、模型、run 时间、总得分、工具调用次数、耗时
  2. Checkpoint 表：逐项 verdict（pass/fail）、判定方式（code/llm）、layer、judge 评语
  3. 完整轨迹时间线：每轮 LLM 回复（token 数，可折叠）+ 工具调用（名称/入参，可展开完整返回）+ final_result
  4. 交付物渲染：`output/diagnosis_report.md`（Markdown 渲染）
  5. 标准答案：`ground_truth.json`
  6. 病例数据：`cleaned_trajectory.csv` 表格
  7. 任务信息：checkpoints 定义（description + judge 类型）
- G4: 刷新机制 = 手动刷新按钮 + 切换病例/run 时重新读取（无自动轮询）
- G5: scanner 层单测 + API 层测试全部通过；现有测试套件不回归

### 不做（Non-Goals）

- 不改动 `website/`（开源 demo，独立维护）
- 不做自动轮询 / WebSocket 实时跟随（Q4 已确认手动刷新）
- 不做登录鉴权、不做局域网/远程访问（只绑 127.0.0.1）
- 不做 e2e 前端自动化测试（人工验收）
- 不做多任务集切换 UI（扫描范围固定 `tasks/oncology-v2`，scanner 留参数化扩展点即可）
- 不改 `eval/runner.py` 的产物格式

## 3. 决策记录（brainstorming 已确认）

| # | 决策 | 用户选择 |
|---|---|---|
| Q1 | 技术路线：A 独立 Python 轻量服务 / B 扩展 Next.js / C 静态 HTML | **A**（项目纯 Python + uv，无 node 依赖，可复用已有解析逻辑，后续还能给 website/ 供 API） |
| Q2 | 详情页内容：概览 / checkpoint 表 / 完整轨迹 / 交付物 / 任务信息 / 标准答案 / 病例 CSV | **全部要**；instruction 放顶部概览（不在任务信息里重复） |
| Q3 | 扫描范围：A 只扫 `tasks/*/runs/` / B 含 `jobs/` 旧布局 | **A**（jobs/ 布局无实际产物，且本次直接清除） |
| Q4 | 刷新：A 手动 / B 自动轮询 | **A** |
| Q5 | 旧 jobs 代码 | **全部清除**（含 v1 runner `run_task.py`） |

## 4. 设计

### 4.1 旧 jobs 约定清理

**删除（7 个文件）**：

| 文件 | 说明 |
|---|---|
| `scripts/job_manager.py` | jobs/ 目录管理（create_job_dir / write_metadata / parse_pytest_results） |
| `scripts/score_jobs.py` | jobs/ 结果汇总（pass@1/pass@k） |
| `scripts/run_batch_task.sh` | 批量 runner，产物写 jobs/ |
| `scripts/task_taxonomy_v1.json` | 仅 score_jobs.py 消费 |
| `scripts/run_task.py` | v1 单任务 runner，目标目录 `tasks/oncology-v1` 已不存在，被 `eval/runner.py` 取代 |
| `tests/oncology_runtime/test_run_task_csv.py` | 测 run_task.py |
| `tests/oncology_runtime/test_local_runner.py` | 测 run_task.py + job_manager + run_batch 链路 |

**修改**：

- `README.md`：目录结构、快速开始、工作流中移除上述 4 个脚本的引用；运行/评测入口改为 `eval/runner.py` 与新的 viewer
- `agent/trajectory.py`：docstring "Consumed by `parse_trajectory.py` and `score_jobs.py`" 更新为当前消费者
- `docs/physicianbench-study/README.md`：旧研究文档，对已删脚本的引用标注 legacy 或改为现行入口

**不动**：`docs/superpowers/plans/`（历史计划记录）、`.github/workflows/deploy.yml`（已核实无引用）。

清理后验收：`rg -n "job_manager|score_jobs|run_batch_task" --glob '!.venv' --glob '!docs/superpowers/plans'` 无残留引用；全量测试通过。

### 4.2 轨迹浏览服务

#### 产物布局（扫描目标，只读）

```
tasks/oncology-v2/<case_id>/
  task.toml                # case_id, task_type, task_label, target_date, deliverable, data_file
  instruction.md           # 题干
  checkpoints.json         # 6 个 checkpoint 定义（code/llm_judge/field_match）
  ground_truth.json        # 标准答案
  cleaned_trajectory.csv   # 病例数据
  runs/<YYYYMMDD-HHMMSS>/
    trajectory.json        # 注意：文件名是 .json，实际是 JSONL（逐行 json.loads）
    scorecard.json         # case_id/task_type/agent_model/checkpoints[]/checkpoint_summary
    output/*.md            # 交付报告
```

轨迹事件类型（JSONL 每行一个事件）：`instruction`、`agent_initialized`（模型/参数元数据）、`llm_response`（prompt/completion tokens、finish_reason、raw_message）、`tool_call`（tool_name/input/output 完整返回）、`final_result`。

#### 模块结构

```
viewer/
  __init__.py
  __main__.py      # uv run python -m viewer → uvicorn 启动，默认 127.0.0.1:8765
  scanner.py       # 纯函数层：扫描 + 解析，不依赖 FastAPI，可单测
  server.py        # FastAPI 应用：3 个 API + 静态挂载
  static/
    index.html     # 单页前端（原生 HTML/JS/CSS，零构建）
    app.js
    style.css
```

依赖（`uv add`）：`fastapi`、`uvicorn`、`markdown`。

#### scanner.py（纯函数，输入根目录 Path）

- `scan_tasks(root) -> list[TaskInfo]`：遍历 `root/*/`，读 task.toml（`tomllib`）+ 统计 runs；返回 case_id、task_type、task_label、target_date、run 数量、最好/最近得分
- `load_task(root, case_id) -> TaskDetail`：instruction.md、checkpoints.json、ground_truth.json、cleaned_trajectory.csv、runs 列表
- `load_run(root, case_id, run_id) -> RunDetail`：
  - scorecard（缺失 → `status="incomplete"`，其余字段照常）
  - trajectory 事件列表（逐行解析 JSONL，坏行跳过并计数）
  - duration：首末事件 `timestamp` 差
  - 交付物：`output/*.md` 原文 + `markdown` 库渲染的 HTML
- 每次调用现读文件，无缓存（手动刷新语义由此保证）

#### server.py API

| 端点 | 返回 |
|---|---|
| `GET /api/tasks` | 病例列表（case_id、task_label、task_type、run 数、最近得分） |
| `GET /api/tasks/{case_id}` | 任务详情 + instruction + checkpoints 定义 + runs 列表（run_id、模型、score、pass/fail、tool_calls、duration、status） |
| `GET /api/tasks/{case_id}/runs/{run_id}` | scorecard + trajectory 事件 + 报告 HTML + ground_truth + CSV 表（服务端转 HTML `<table>`） |

- 只绑 `127.0.0.1`，无鉴权
- 未知 case/run → 404 + JSON 错误体
- `markdown` 渲染开启 fenced_code 扩展

#### 前端（单页，无构建）

- **左侧栏**：病例列表。每项：case_id 前 8 位缩写 + task_label + run 数 + 最近得分徽标（6/6 绿 / 部分黄 / 全红）
- **右侧主区**：
  - 顶部概览卡：任务标签、task_type、target_date、模型、run 时间戳、总得分、工具调用次数、耗时、**instruction 全文**（Markdown 渲染）
  - run 选择器（同一 case 多个 run 时）：下拉或 chip，显示 `时间戳 · 模型 · score`
  - 标签页：
    - **Checkpoint 情况**：表格（checkpoint_id、layer、description、verdict、judge 类型、comment）
    - **完整轨迹**：时间线。`llm_response` 卡片（step 号、tokens、finish_reason，正文可折叠，含 reasoning）；`tool_call` 卡片（工具名 + 入参 JSON，返回内容 `<details>` 折叠，默认收起，超长截断 + "展开完整"）；末尾 `final_result`
    - **交付物**：报告 HTML
    - **标准答案**：ground_truth.json 格式化
    - **病例数据**：cleaned_trajectory.csv 表格（服务端已转 HTML）
- 右上角"刷新"按钮：重拉当前视图数据
- 空状态：无任务目录 / 无 run → 友好提示

#### 错误处理

- run 缺 scorecard（中断/崩溃）→ 列表标"未完成"，详情页正常显示轨迹
- JSONL 坏行 → 跳过 + 页面提示"N 行解析失败"
- case 缺 ground_truth / cleaned_trajectory → 对应标签页显示缺失提示，不影响其他页

## 5. 测试

- `tests/test_viewer_scanner.py`：tmp_path 构造假任务树（含正常 run、缺 scorecard 的 run、坏 JSONL 行），断言 scan/load 结果
- `tests/test_viewer_server.py`：FastAPI TestClient（httpx 已在依赖中）测 3 个 API 的成功路径 + 404
- 回归：清理 jobs 后全量 `pytest` 通过
- 前端：人工验收（用现有 2 个 case / 3 个 run 的真实数据过一遍七块内容）

## 6. 验收标准

1. `git grep` 无 jobs 约定残留（§4.1 命令）
2. `uv run python -m viewer` 启动后，浏览器打开 8765 端口，能看到 2 个病例、3 个 run
3. 选中 `00151e6a…` 的 `20260820-210036` run：概览显示 qwen3.8 / 6.0 分 / 工具调用次数 / 耗时；checkpoint 表 6 项全 pass；轨迹时间线可见 11 次工具调用的入参与返回；报告渲染出 PR 结论
4. 刷新按钮、空状态、缺 scorecard 场景行为符合 §4.2
5. 全量测试通过

## 7. 实施注意

- 开工前：main 上有未提交改动（eval-loop 收尾：`agent/trajectory.py`、`generated/v2/*`、两个 case 的产物文件）。先将其整理提交，再开 `feat/trajectory-viewer` 分支
- 不提交 `data/oncology_complete_trajectory/prompt_test/`（实验临时数据，与本次无关）
- `uv.lock` 的既有改动随依赖更新一并处理
