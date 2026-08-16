# Oncology 诊断任务生成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 5 个固定 oncology CSV 病例通过 LangGraph 生成诊断任务，并让现有 Agent 在独立清洗数据上本地运行和评测。

**Architecture:** 第一阶段使用 LangGraph 编排完整病例读取、事件组构建、目标诊断事件组选择、任务提示词生成、清洗数据物化、校验和任务导出。第二阶段复用 MiniAgent、CSV 查询工具和 trajectory，但把工具数据源切换到 `cleaned/<case_id>.csv`，并在 Agent 完成后执行规则评估和 LLM judge。两个阶段分别读取 `generation_env` 和 `agent_eval_env` 的模型、API key、base URL、环境变量及其他 key-value 配置。

**Tech Stack:** Python 3.10+, LangGraph, OpenAI-compatible `LLMClient`, pytest, CSV 标准库。

---

## Task 1: 建立事件组时间线与清洗数据

**Files:**
- Modify: `pipeline/oncology_generation/schemas.py`
- Modify: `pipeline/oncology_generation/nodes.py`
- Create: `pipeline/oncology_generation/cleaning.py`
- Test: `tests/oncology_generation/test_event_groups.py`
- Test: `tests/oncology_generation/test_cleaning.py`

- [ ] **Step 1: Write failing tests for event grouping.**

测试使用包含两个日期、同一 `group_id` 多行、同一天两个不同 `group_id` 的最小 CSV 事件列表，验证 `build_event_groups(events)` 返回按原始行首次出现顺序排列的事件组，并保留每组全部原始行。

预期接口：

```python
groups = build_event_groups(events)
assert [group.group_id for group in groups] == ["g1", "g2", "g3"]
assert groups[0].events == events[:2]
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `pytest tests/oncology_generation/test_event_groups.py -q`

Expected: FAIL because `build_event_groups` and the event-group type do not exist.

- [ ] **Step 3: Implement the event-group type and grouping function.**

在 `schemas.py` 定义不可变或只读语义清晰的 `EventGroup`，至少包含 `group_id`、`event_date`、`first_source_row`、`category` 和 `events`。在 `nodes.py` 或独立 helper 中按 `_source_row` 数字排序；每个 group 的 `first_source_row` 决定时间线顺序，不按随机 UUID 的字典序排序。

- [ ] **Step 4: Write failing tests for materializing a cleaned case.**

测试构造事件组 `g1, g2, g3`，选择 `g2` 为目标，调用：

```python
result = materialize_cleaned_case(
    source_csv, cleaned_csv, target_group_id="g2"
)
assert result.target_events == g2_events
assert read_groups(cleaned_csv) == ["g1"]
```

同时验证源文件内容未变化、目标组全部行被移除、同一天目标组之前的组保留、目标组之后的组移除。

- [ ] **Step 5: Run the cleaning tests and verify they fail.**

Run: `pytest tests/oncology_generation/test_cleaning.py -q`

Expected: FAIL because the cleaning helper does not exist.

- [ ] **Step 6: Implement non-destructive cleaning.**

新增 `materialize_cleaned_case(source_csv: Path, cleaned_csv: Path, target_group_id: str) -> CleaningResult`。读取完整源 CSV，按事件组首次原始行定位目标组，将目标组及其后的组过滤掉，把目标组全部行保存到 `CleaningResult.target_events`，再写入独立的 `cleaned_csv`。禁止修改、删除或覆盖源 CSV；输出目录自动创建。

- [ ] **Step 7: Run focused tests.**

Run: `pytest tests/oncology_generation/test_event_groups.py tests/oncology_generation/test_cleaning.py -q`

Expected: all tests pass.

- [ ] **Step 8: Commit the data-boundary unit.**

```bash
git add pipeline/oncology_generation/schemas.py pipeline/oncology_generation/nodes.py pipeline/oncology_generation/cleaning.py tests/oncology_generation/test_event_groups.py tests/oncology_generation/test_cleaning.py
git commit -m "feat(oncology): 增加诊断事件组清洗"
```

## Task 2: 调整 LangGraph 任务生成流程

**Files:**
- Modify: `pipeline/oncology_generation/schemas.py`
- Modify: `pipeline/oncology_generation/nodes.py`
- Modify: `pipeline/oncology_generation/graph.py`
- Test: `tests/oncology_generation/test_graph_validation.py`
- Create: `tests/oncology_generation/test_diagnosis_generation.py`

- [ ] **Step 1: Write failing tests for the generation state contract.**

扩展 `GenerationState`，测试要求状态能表达 `event_groups`、`target_group_id`、`target_events`、`task_draft`、`cleaned_path` 和 `validation_errors`。测试还要验证目标事件组允许来自任意 category，但必须真实存在且至少包含一条诊断性 `feature_name/value` 信息。

- [ ] **Step 2: Run the tests and verify they fail.**

Run: `pytest tests/oncology_generation/test_diagnosis_generation.py -q`

Expected: FAIL because the new state fields and target-group validation are absent.

- [ ] **Step 3: Replace segment selection with structured target-group selection.**

将 `select_anchor` 改为 `select_target_group`。传给模型的 prompt 明确要求返回：

```json
{
  "target_group_id": "...",
  "selection_rationale": "...",
  "role": "...",
  "instruction": "...",
  "deliverable": "..."
}
```

prompt 必须说明：目标可以是任意 category，但必须是明确诊断性事件组；任务提示词不得包含目标组的 `value`。解析后用 `group_id` 精确索引事件组，不接受模型自行改写的事件字段作为来源。

- [ ] **Step 4: Implement the fixed LangGraph node sequence.**

将图节点收敛为：

```text
load_case -> build_timeline -> select_target_group -> materialize_cleaned_case -> validate -> persist
```

`select_target_group` 同时生成任务草稿，不加入任务类型路由、复杂 environment profile 或 judge 生成节点。`materialize_cleaned_case` 使用 `data_root / "raw/csv"` 读取源文件，并写入 `data_root / "cleaned" / f"{case_id}.csv"`。

- [ ] **Step 5: Strengthen deterministic validation.**

在 `validate_state` 中检查：目标组存在、目标组全部行可追溯、清洗文件不含目标组和后续组、任务 instruction 不含目标组 `value`、输出路径位于 cleaned 目录。校验失败时状态为 `needs_revision`，不能导出任务。

- [ ] **Step 6: Run generation tests.**

Run: `pytest tests/oncology_generation/test_graph_validation.py tests/oncology_generation/test_diagnosis_generation.py -q`

Expected: all tests pass, including a fixture where `category` is not `诊断` but `feature_name` is `病理诊断`.

- [ ] **Step 7: Commit the LangGraph generation change.**

```bash
git add pipeline/oncology_generation tests/oncology_generation/test_graph_validation.py tests/oncology_generation/test_diagnosis_generation.py
git commit -m "feat(oncology): 改造诊断任务生成图"
```

## Task 3: 导出任务契约并支持 5 个 pilot case

**Files:**
- Modify: `scripts/generate_oncology_task.py`
- Modify: `scripts/generate_all_oncology_tasks.py`
- Modify: `data/oncology_complete_trajectory/README.md`
- Modify: `tests/oncology_generation/test_export.py`
- Modify: `tests/oncology_generation/test_batch_generation.py`

- [ ] **Step 1: Write failing export tests for the new file contract.**

更新测试，使任务目录只包含 `instruction.md`、`task.toml`、`ground_truth.json` 和 `tests/`，并验证清洗 CSV 位于 `data/oncology_complete_trajectory/cleaned/<case_id>.csv`，不位于任务目录。ground truth 必须保存目标组全部行、`target_group_id`、source row 引用和目标日期。

- [ ] **Step 2: Run export tests and verify they fail.**

Run: `pytest tests/oncology_generation/test_export.py tests/oncology_generation/test_batch_generation.py -q`

Expected: FAIL because the current exporter writes checkpoint-oriented ground truth and does not materialize cleaned data.

- [ ] **Step 3: Implement the task exporter.**

调整 `export_task(state, output_root, cleaned_root)`：使用 `case_id` 作为任务目录名；写入不含答案的 `instruction.md`；写入 `task.toml` 的 `case_id`、`data_root` 相对路径和任务标签；写入完整目标事件组到 `ground_truth.json`；生成沿用现有任务测试入口的 `tests/test_outputs.py`。

- [ ] **Step 4: Restrict batch generation to the five fixed cases.**

为 `generate_all_oncology_tasks.py` 增加显式 case 列表参数或默认 pilot 列表，默认只处理设计文档中的 5 个 `case_id`；保留失败隔离和 review queue。每个 case 生成失败不影响其他 case，已有任务目录可被 resume 跳过。

- [ ] **Step 5: Document the raw/cleaned/task separation.**

更新数据 README，明确 raw CSV 只读、cleaned CSV 是任务运行输入、task 目录不保存病例数据，以及生成命令和 5 个 pilot case 的默认范围。

- [ ] **Step 6: Run export and batch tests.**

Run: `pytest tests/oncology_generation/test_export.py tests/oncology_generation/test_batch_generation.py -q`

Expected: all tests pass; no test writes outside its temporary directory.

- [ ] **Step 7: Commit the task export unit.**

```bash
git add scripts/generate_oncology_task.py scripts/generate_all_oncology_tasks.py data/oncology_complete_trajectory/README.md tests/oncology_generation/test_export.py tests/oncology_generation/test_batch_generation.py
git commit -m "feat(oncology): 导出诊断任务与清洗数据"
```

## Task 4: 增加双阶段模型环境并切换本地 Agent 运行

**Files:**
- Modify: `agent/llm_client.py`
- Modify: `scripts/run_task.py`
- Modify: `scripts/run_eval.py`
- Create: `scripts/pipeline_env.py`
- Create: `.env.example`
- Test: `tests/oncology_runtime/test_local_runner.py`

- [ ] **Step 1: Define the two environment contracts.**

在 `scripts/pipeline_env.py` 定义 `ModelEnv` 和 `load_model_env(prefix: str) -> ModelEnv`。支持 `GENERATION_MODEL`/`GENERATION_API_KEY`/`GENERATION_BASE_URL` 与 `AGENT_EVAL_MODEL`/`AGENT_EVAL_API_KEY`/`AGENT_EVAL_BASE_URL`，并保留未设置显式 key 时对现有 `.env` 自动探测的兼容路径。`.env.example` 只能包含变量名和示例占位符，不写真实密钥。

- [ ] **Step 2: Write failing tests for environment isolation.**

测试设置两个前缀环境变量，断言两个 `ModelEnv` 的 model、key 和 base URL 独立；未设置阶段变量时，验证现有自动 backend 探测仍可用。

- [ ] **Step 3: Run the environment tests and verify they fail.**

Run: `pytest tests/oncology_runtime/test_local_runner.py -q`

Expected: FAIL because the stage-specific environment loader does not exist.

- [ ] **Step 4: Extend `LLMClient` for explicit stage configuration.**

让 `LLMClient` 接受独立的 `api_key` 和 `base_url`，同时保留当前未传参时的 backend auto-detection。任务生成脚本使用 `GENERATION_*`，Agent 和 judge 使用 `AGENT_EVAL_*`。

- [ ] **Step 5: Remove FHIR lifecycle from the CSV runner path.**

在 `scripts/run_task.py` 增加本地 CSV 模式：默认把 `data_root / "cleaned"` 作为工具根目录，调用现有 `register_all_tools(registry, data_root=...)`，不执行 Docker、端口映射或 FHIR readiness 检查。保留现有 FHIR 参数仅作为明确兼容分支，CSV 任务不能进入该分支。

- [ ] **Step 6: Add runtime isolation tests.**

用临时 `raw/csv` 和 `cleaned` 创建同一 case 的不同内容，mock `MiniAgent` 和 `register_all_tools`，断言 runner 传入的是 cleaned root，且工具查询结果只来自 cleaned 文件。

- [ ] **Step 7: Run runtime tests.**

Run: `pytest tests/oncology_runtime/test_local_runner.py tests/oncology_tools/test_csv_event_store.py -q`

Expected: all tests pass and no Docker command is invoked.

- [ ] **Step 8: Commit the local runtime unit.**

```bash
git add agent/llm_client.py scripts/pipeline_env.py scripts/run_task.py scripts/run_eval.py .env.example tests/oncology_runtime/test_local_runner.py
git commit -m "feat(runtime): 支持双环境本地诊断评测"
```

## Task 5: 增加诊断规则评估和 LLM judge

**Files:**
- Create: `utils/diagnosis_eval.py`
- Modify: `tasks/oncology-v1/<case_id>/tests/test_outputs.py` via exporter template
- Modify: `scripts/run_eval.py`
- Test: `tests/oncology_runtime/test_diagnosis_eval.py`

- [ ] **Step 1: Write failing tests for rule evaluation.**

覆盖三种结果：Agent 输出包含目标组关键诊断字段时为 `correct`；只包含部分字段时为 `partially_correct`；不包含诊断性字段时为 `incorrect`。测试输入使用 ground truth 的 `feature_name/value` 列表，不调用外部模型。

- [ ] **Step 2: Implement deterministic rule evaluation.**

提供：

```python
evaluate_diagnosis_rules(agent_text: str, target_events: list[dict[str, str]]) -> dict
```

返回 `label`、命中字段、未命中字段和分数；匹配逻辑至少支持 Unicode 文本包含和去空白后的包含，不做未经定义的医学同义词推断。

- [ ] **Step 3: Add the LLM judge prompt and client call.**

提供固定 judge 模板，将真实目标事件组和 Agent 最终输出作为两个明确区块传入 `agent_eval_env` 的模型。要求模型只返回 JSON：`label`、`score`、`reason`。解析失败或模型调用失败时写入 evaluator error，不伪装成 Agent 失败。

- [ ] **Step 4: Integrate both evaluators into `run_eval.py`.**

pytest 继续负责任务输出存在性和基础契约；`run_eval.py` 在读取 Agent 最终输出后执行规则评估和 judge，并把结果写入 `logs/verifier/diagnosis_eval.json`。ground truth 从任务目录读取，绝不放入 Agent tool registry。

- [ ] **Step 5: Run evaluator tests.**

Run: `pytest tests/oncology_runtime/test_diagnosis_eval.py tests/oncology_generation/test_export.py -q`

Expected: all tests pass without网络调用；LLM judge 使用 fake client 测试 JSON 解析和失败路径。

- [ ] **Step 6: Commit the evaluation unit.**

```bash
git add utils/diagnosis_eval.py scripts/run_eval.py tests/oncology_runtime/test_diagnosis_eval.py
git commit -m "feat(eval): 增加诊断规则与模型评估"
```

## Final verification

- [ ] Run the complete focused suite:

```bash
pytest tests/oncology_data tests/oncology_tools tests/oncology_generation tests/oncology_runtime -q
```

- [ ] Generate the five pilot tasks using mocked generation responses first; verify each task has a distinct cleaned CSV and ground truth group.

- [ ] With configured `generation_env`, run one real task generation for each fixed case and manually inspect the selected group and instruction before running Agent.

- [ ] With configured `agent_eval_env`, run one local Agent task and verify trajectory, workspace, cleaned-data-only tool access, rule result and judge result.

- [ ] Record any rejected case in `generated/review_queue.jsonl`; do not silently export a task whose target group or data boundary failed validation.
