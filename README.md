# PhysicianBench（PMC 版）

基于我们自己的 PMC 肿瘤病例轨迹数据构建的临床诊断 benchmark。

每个任务考察的核心能力是：**Agent 只能访问诊断时点之前已公开的病例数据，必须通过工具查询、整合证据，推断出目标诊断结论。**

## 数据

- **全量数据**：`data/oncology_complete_trajectory/raw/csv/` 下 **1491 例**完整肿瘤病例轨迹（共 64,965 行事件级记录），由 PMC 论文病例报告抽取而来。事件按类别组织：病史、检验、影像、病理、诊断、手术、用药、评估、病程、不良反应、会诊、入院、出院、其他。
- **小批量验证集（pilot）**：从全量中固定的 **5 个 case**，用于先跑通端到端流程，再扩展全量：

  | case_id | 状态 |
  | --- | --- |
  | `71af50c891bd0e80cd017c8beb2bb446` | 已生成任务 |
  | `15c35bb60e48e62f9beb9fd127248e03` | 待生成 |
  | `7df4bd9af484dcec897b2f2726e01db2` | 已生成任务 |
  | `01864b911256ca7332f7974165d7aeb8` | 待生成 |
  | `aca554ac1716cf2fb7e2b94d80590e52` | 已生成任务 |

  > 这 5 个 case 是 1491 例全量数据的**子集**，不是额外数据。批量生成脚本默认就只处理这 5 个。

## 核心流程（两阶段模型环境）

```
┌─ 阶段一：任务生成（GENERATION 环境） ─────────────────────────┐
│  生成模型查看完整病例 → 选择一个诊断性事件组作为答案             │
│  → 程序移除该事件组及其之后的事件 → 物化 cleaned CSV            │
│  → 校验（无泄漏 / 可溯源 / 工具约束）→ 导出任务目录             │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ 阶段二：Agent 评测（AGENT_EVAL 环境） ───────────────────────┐
│  被测 Agent 只能查询 cleaned CSV（目标诊断被移除）              │
│  → 通过 15 个分类查询工具 + write_file 完成诊断                │
│  → 交付 output/diagnosis_report.md                            │
│  → pytest 测试 + 诊断规则评估（exact/semantic）+ LLM judge    │
└──────────────────────────────────────────────────────────────┘
```

两个阶段的模型配置完全独立（不同的模型、服务商、参数），通过环境变量区分：

```bash
GENERATION_MODEL / GENERATION_API_KEY / GENERATION_BASE_URL
AGENT_EVAL_MODEL / AGENT_EVAL_API_KEY / AGENT_EVAL_BASE_URL
```

## 目录结构

```
├── agent/                      # MiniAgent：LLM 工具调用循环 + trajectory 日志
├── pipeline/oncology_generation/  # LangGraph 生成流水线（节点 / 图 / 校验 / 泄漏检测）
├── tools/                      # CSV 分类查询工具、文件工具、FHIR 兼容层
├── tasks/oncology-v1/<case_id>/    # 生成的任务（instruction + 测试 + ground_truth）
├── data/oncology_complete_trajectory/
│   ├── raw/csv/                # 1491 例原始病例（只读，绝不修改）
│   ├── cleaned/                # Agent 可查询的清洗数据（任务运行输入）
│   ├── generated/              # 生成中间态与 review_queue.jsonl
│   ├── index/manifest.json     # 数据清单（文件数 / 行数 / sha256）
│   └── index/build_index.py    # 只读索引构建
├── scripts/
│   ├── generate_oncology_task.py        # 单例任务生成
│   ├── generate_all_oncology_tasks.py   # 批量生成（默认 5 个 pilot case，失败隔离）
│   ├── run_task.py                      # 单任务：Agent 运行 + pytest 评测
│   ├── run_batch_task.sh                # 批量运行（支持 --resume / --n_runs / --model）
│   ├── run_eval.py                      # 对 job 目录重跑诊断规则评估
│   ├── score_jobs.py                    # 汇总 pass@k / pass^k / 平均轮次
│   └── job_manager.py                   # job 目录管理（创建 / resume）
├── utils/                      # 诊断评估（exact / semantic / judge）与评测辅助
└── tests/                      # 126 个单元测试（生成 / 运行 / 工具 / 数据 / 评估）
```

## 快速开始

```bash
# 1. 安装依赖（Python >= 3.10，使用 uv）
uv sync

# 2. 配置双模型环境
cp .env.example .env   # 填写 GENERATION_* 和 AGENT_EVAL_*

# 3. 构建只读数据索引（可选，生成 manifest）
uv run python data/oncology_complete_trajectory/index/build_index.py

# 4. 生成任务（默认处理 5 个 pilot case，已完成的自动跳过）
uv run python scripts/generate_all_oncology_tasks.py
# 指定 case：
uv run python scripts/generate_all_oncology_tasks.py --case-id <case_id> [<case_id> ...]

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

## 任务格式

每个任务目录 `tasks/oncology-v1/<case_id>/` 包含：

| 文件 | 说明 |
| --- | --- |
| `instruction.md` | 中文诊断指令：当前诊断时点、任务要求、交付物约定 |
| `task.toml` | 元数据：case_id、cleaned 数据相对路径、标签 |
| `ground_truth.json` | 目标事件组的完整答案（事件明细 + 源行号溯源） |
| `tests/test_outputs.py` | pytest 测试：交付物存在性 + ground truth 完整性 |

任务目录**不保存病例 CSV**；Agent 运行时通过 `task.toml` 的 `data_root` 相对路径引用 `cleaned/<case_id>.csv`。

## Agent 与工具

被测 Agent（`agent/mini_agent.py`）是一个带防护的 LLM 工具调用循环：最大步数限制、重复错误/重复调用检测、工具输出截断、完整 trajectory 日志。可用工具：

- **15 个分类查询工具**：`search_oncology_<category>`（病史 / 检验 / 影像 / 病理 / 诊断 / 手术 / 用药 / 评估 / 病程 / 不良反应 / 会诊 / 入院 / 出院 / 其他 / 全量），支持 subject / feature / 日期 / group_id 过滤。
- **`write_file`**：写入 workspace 内的交付文件（如 `output/diagnosis_report.md`）。

每次调用的结果都带 `_source_row` 溯源信息，可回溯到原始 CSV 行。

## 安全设计

- **防泄漏**：生成阶段校验目标诊断片段不得出现在 instruction 中（CJK/ASCII 归一化后比对）；cleaned CSV 移除目标事件组及其之后的事件，Agent 无法直接查到答案。
- **防路径穿越**：case_id 校验 + cleaned 路径必须落在数据根内 + 拒绝符号链接。
- **raw 只读**：所有流水线对 `raw/csv` 只读不写；生成失败写入 `generated/review_queue.jsonl`，单个 case 失败不影响其他 case。

## 测试

```bash
uv run pytest            # 126 个测试：生成流水线 / 运行契约 / 工具 / 数据索引 / 清洗 / 诊断评估
```
