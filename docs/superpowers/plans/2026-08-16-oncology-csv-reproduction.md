# Oncology CSV Reproduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 oncology trajectory CSV 接入 PhysicianBench，使单个 case 能生成任务、调用 14 类 CSV 事件工具并通过 checkpoint 评测，再扩展到全量 case。

**Architecture:** 当前仓库作为 CSV 专用复现副本，原始 CSV 通过项目内标准目录接入；事件存储模块负责读取和过滤原始行，14 个工具包装同一查询接口并固定 category。LangGraph 负责从真实时间线生成任务和 checkpoint，CSV 专用运行器复用现有 Agent loop、trajectory、workspace 和 pytest 评测。

**Tech Stack:** Python 3.10+, LangGraph, pytest, OpenAI-compatible function calling, Docker（仅用于可复现运行环境）。

## Global Constraints

- 原版 PhysicianBench 保留在另一份独立克隆中；当前仓库允许破坏性改造，不保留 FHIR/CSV 双后端。
- 原始 CSV 不被改写；工具返回的事件必须能追溯到原始行。
- 第一阶段只做一个 case 的垂直切片；生成契约稳定后再批量处理全部 1491 个 case。
- 14 个 category 均提供独立查询工具；工具只检索和结构化展示，不替 Agent 做医学总结。
- checkpoint 第一版只支持 retrieval、reasoning、documentation；只有数据存在明确动作事件时才增加 action。
- 每个任务完成一个独立可测试变更后再提交，commit description 和 body 使用中文。

---

### Task 1: 接入 CSV 数据并建立只读索引

**Files:**
- Create: `data/oncology_complete_trajectory/README.md`
- Create: `data/oncology_complete_trajectory/index/build_index.py`
- Create: `data/oncology_complete_trajectory/index/manifest.json`
- Modify: `.gitignore`
- Test: `tests/oncology_data/test_index.py`

**Interfaces:**
- Produces `build_index(data_root: Path) -> dict` and `load_case_csv(case_id: str, data_root: Path) -> Path`.
- `manifest.json` contains `data_root`, `file_count`, `row_count`, sorted category counts, and per-file SHA-256.

- [ ] **Step 1: Write failing tests** for 1491-file discovery, CSV header validation, manifest counts, and rejection of an unknown case id.
- [ ] **Step 2: Run tests** with `pytest tests/oncology_data/test_index.py -q`; verify failures describe missing index functions.
- [ ] **Step 3: Implement the read-only index builder** using `csv.DictReader`; validate the 17 required columns and preserve source paths. Do not load all files into one generated dataset.
- [ ] **Step 4: Add the project data README** documenting the standard path, the source path, the symlink setup command, and that raw CSV is not committed.
- [ ] **Step 5: Add ignore rules** for generated index caches and generated LangGraph state while keeping the README and manifest trackable.
- [ ] **Step 6: Run tests** and verify the manifest on the real dataset reports 1491 files and 64,965 rows.
- [ ] **Step 7: Commit** `git add data/oncology_complete_trajectory tests/oncology_data .gitignore && git commit -m "feat(data): 接入肿瘤病例CSV索引"`.

### Task 2: 实现统一事件查询模块

**Files:**
- Create: `tools/csv_event_store.py`
- Create: `tools/csv_event_types.py`
- Test: `tests/oncology_tools/test_csv_event_store.py`

**Interfaces:**
- `EventQuery(case_id: str, category: str | None = None, subject: str | None = None, feature_name: str | None = None, event_date: str | None = None, group_id: str | None = None, limit: int = 100)`.
- `CsvEventStore(data_root: Path)` with `query(query: EventQuery) -> list[dict[str, str]]`.
- Returned dictionaries include `case_id`, `encnt_no`, `group_id`, `subject`, `feature_name`, `feature_type`, `value`, `actual_value`, `extra_value`, `unit`, `method`, `source`, `_record_source`, `event_date`, `category`, and `pipeline_version`.

- [ ] **Step 1: Write failing tests** for category filtering, exact subject/feature filtering, date filtering, group filtering, deterministic ordering, limit enforcement, and missing-file errors.
- [ ] **Step 2: Run the focused tests** and verify they fail before the store exists.
- [ ] **Step 3: Implement `EventQuery` and `CsvEventStore`** with streaming `csv.DictReader`, UTF-8 BOM support, stable ordering by `event_date`, `encnt_no`, `group_id`, and source row number.
- [ ] **Step 4: Add explicit validation** for supported categories and positive limits; return an empty list for valid filters with no matches.
- [ ] **Step 5: Run tests** including a fixture copied from one real case and verify raw fields are unchanged.
- [ ] **Step 6: Commit** `git add tools/csv_event_store.py tools/csv_event_types.py tests/oncology_tools && git commit -m "feat(tools): 增加CSV事件查询存储"`.

### Task 3: 替换并扩展 14 类 Agent 工具

**Files:**
- Create: `tools/csv_category_tools.py`
- Modify: `agent/tool_registry.py`
- Modify: `tools/file_tools.py` only if registration signatures require it
- Test: `tests/oncology_tools/test_csv_category_tools.py`

**Interfaces:**
- `CATEGORY_TOOL_SPECS: tuple[CategoryToolSpec, ...]` contains the 14 Chinese categories and English tool names.
- Each registered function has signature `func(case_id: str, subject: str | None = None, feature_name: str | None = None, event_date: str | None = None, group_id: str | None = None, limit: int = 100) -> dict` and returns `{"category": ..., "events": [...], "count": ...}`.
- `register_all_tools(registry, data_root: Path | None = None)` registers 14 CSV query tools plus `write_file`.

- [ ] **Step 1: Write failing tests** asserting exactly 14 category tools, correct category-to-tool mapping, descriptions that mention CSV event retrieval, and consistent parameter schemas.
- [ ] **Step 2: Run the registry tests** and confirm the old FHIR tool set fails the new contract.
- [ ] **Step 3: Implement thin category wrappers** over `CsvEventStore`; do not duplicate filtering logic in each wrapper.
- [ ] **Step 4: Update tool descriptions** to describe the subject-feature-value event shape and the category each tool searches.
- [ ] **Step 5: Add category display configuration** for first-version output ordering without changing raw event fields.
- [ ] **Step 6: Run tests** and verify a real case can query at least one event from every category that exists in that case.
- [ ] **Step 7: Commit** `git add agent/tool_registry.py tools/csv_category_tools.py tests/oncology_tools && git commit -m "feat(tools): 适配14类CSV事件查询工具"`.

### Task 4: 构建 LangGraph 任务与 checkpoint 生成图

**Files:**
- Create: `pipeline/oncology_generation/state.py`
- Create: `pipeline/oncology_generation/nodes.py`
- Create: `pipeline/oncology_generation/graph.py`
- Create: `pipeline/oncology_generation/schemas.py`
- Create: `pipeline/oncology_generation/prompts.py`
- Test: `tests/oncology_generation/test_graph_validation.py`
- Modify: `pyproject.toml` to add the pinned LangGraph dependency.

**Interfaces:**
- `GenerationState(TypedDict)` fields: `case_id`, `raw_events`, `candidate_segments`, `selected_segment`, `task_draft`, `checkpoint_drafts`, `validation_errors`, `review_status`.
- `build_generation_graph() -> CompiledStateGraph`.
- `run_generation(case_id: str, data_root: Path, client: LLMClient) -> GenerationState`.
- Checkpoint schema requires `kind`, `objective`, `tool_names`, `evidence_refs`, `verification`, and `pass_criteria`.

- [ ] **Step 1: Write failing schema tests** for required evidence references, supported checkpoint kinds, and rejection of references not found in `raw_events`.
- [ ] **Step 2: Run validation tests** and confirm missing schemas/nodes fail.
- [ ] **Step 3: Implement typed Pydantic/dataclass schemas** for task drafts, evidence references, and retrieval/reasoning/documentation checkpoints.
- [ ] **Step 4: Implement deterministic nodes** `load_case`, `build_timeline`, and `validate`; validation must check tool names, event references, checkpoint kinds, and answer leakage markers.
- [ ] **Step 5: Implement model nodes** `select_anchor`, `draft_task`, and `draft_checkpoints` with structured JSON output and retry-on-parse-error behavior.
- [ ] **Step 6: Implement the review branch** so failed validation returns to the relevant draft node and successful review reaches `export`.
- [ ] **Step 7: Add graph persistence** under `data/oncology_complete_trajectory/generated/<case_id>/` with raw model responses and final state.
- [ ] **Step 8: Run tests** using a deterministic fake LLM client and one real case fixture; verify all exported evidence references resolve.
- [ ] **Step 9: Commit** `git add pipeline/oncology_generation pyproject.toml tests/oncology_generation && git commit -m "feat(pipeline): 增加LangGraph任务检查点生成"`.

### Task 5: 导出首个 case 为框架任务并实现 checkpoint

**Files:**
- Create: `scripts/generate_oncology_task.py`
- Create: `tasks/oncology-v1/<task_id>/task.toml`
- Create: `tasks/oncology-v1/<task_id>/instruction.md`
- Create: `tasks/oncology-v1/<task_id>/ground_truth.json`
- Create: `tasks/oncology-v1/<task_id>/tests/test_outputs.py`
- Test: `tests/oncology_generation/test_export.py`

**Interfaces:**
- `export_task(state: GenerationState, output_root: Path) -> Path` writes a complete task directory and refuses to overwrite an existing approved task.
- Generated `ground_truth.json` stores only evidence references and expected criteria; it does not expose the answer in `instruction.md`.

- [ ] **Step 1: Write failing export tests** for required task files, no answer leakage, evidence reference resolution, and idempotent refusal to overwrite.
- [ ] **Step 2: Implement the exporter** mapping structured graph output to the existing task directory conventions.
- [ ] **Step 3: Implement deterministic retrieval checks** against trajectory tool calls and returned event references.
- [ ] **Step 4: Implement reasoning and documentation checks** using output text plus the evidence-backed rubric; keep them independent so one failure is diagnosable.
- [ ] **Step 5: Run the generator for one selected real case**, review the generated instruction, checkpoint criteria, and evidence references manually.
- [ ] **Step 6: Run the generated task tests** with a fixture trajectory/output and verify expected pass/fail behavior.
- [ ] **Step 7: Commit** `git add scripts/generate_oncology_task.py tasks/oncology-v1 tests/oncology_generation && git commit -m "feat(tasks): 导出首个肿瘤CSV任务"`.

### Task 6: 改造 CSV 专用运行器并支持 Docker 复现

**Files:**
- Modify: `scripts/run_task.py`
- Modify: `scripts/run_eval.py`
- Modify: `scripts/run_batch_task.sh`
- Create: `docker/oncology-csv/Dockerfile`
- Create: `docker/oncology-csv/README.md`
- Test: `tests/oncology_runtime/test_run_task_csv.py`

**Interfaces:**
- `run_task.py TASK_DIR --data-root PATH --model MODEL --max-steps N` runs without starting FHIR.
- `run_agent(task_dir, job_dir, data_root, model, ...) -> bool` registers CSV tools and writes the same trajectory/workspace artifacts.
- `run_evaluation(task_dir, job_dir) -> bool` runs generated pytest checkpoints without a FHIR URL.

- [ ] **Step 1: Write failing runner tests** asserting no FHIR container command is invoked, CSV tools receive the selected data root, and job artifacts use the existing layout.
- [ ] **Step 2: Implement CSV-only lifecycle** in `run_task.py`; preserve model, max-step, temperature, trajectory, workspace, and metadata behavior.
- [ ] **Step 3: Remove FHIR URL assumptions** from evaluation and batch scripts while retaining clear errors for missing task files or data roots.
- [ ] **Step 4: Add the Docker image** with read-only mounts for `data/oncology_complete_trajectory/raw/csv` and task directories; do not bake raw data into the image.
- [ ] **Step 5: Run the first complete local task** and capture the command, tool calls, generated output, and checkpoint results under `jobs/`.
- [ ] **Step 6: Run the same task in Docker** and compare query results and checkpoint outcomes with the local run.
- [ ] **Step 7: Commit** `git add scripts docker tests/oncology_runtime && git commit -m "feat(runtime): 改造CSV专用任务运行器"`.

### Task 7: 批量生成与全量质量门禁

**Files:**
- Create: `scripts/generate_all_oncology_tasks.py`
- Create: `pipeline/oncology_generation/review_queue.py`
- Create: `tests/oncology_generation/test_batch_generation.py`
- Create: `docs/oncology-csv/README.md`

**Interfaces:**
- `generate_all_cases(data_root: Path, output_root: Path, max_workers: int = 1) -> BatchSummary`.
- `BatchSummary` contains processed, exported, rejected, and review-queue counts plus per-case error paths.

- [ ] **Step 1: Write failing batch tests** for resume behavior, isolated per-case failures, deterministic output paths, and review queue entries.
- [ ] **Step 2: Implement sequential batch generation** first; each case gets its own LangGraph state directory and task id.
- [ ] **Step 3: Add review queue serialization** with validation errors and source case ids; do not silently discard rejected cases.
- [ ] **Step 4: Add optional bounded parallelism** only after sequential tests pass, preserving one output directory per case.
- [ ] **Step 5: Run a small batch** of 10 cases and inspect exported task/checkpoint quality before starting all 1491 cases.
- [ ] **Step 6: Run full generation and summarize counts**; leave failed cases in the review queue for later iteration.
- [ ] **Step 7: Commit** `git add scripts pipeline/oncology_generation/review_queue.py tests/oncology_generation docs/oncology-csv && git commit -m "feat(batch): 增加全量肿瘤病例生成流程"`.

## Verification Checklist

- [ ] `pytest tests/oncology_data tests/oncology_tools tests/oncology_generation tests/oncology_runtime -q`
- [ ] One case generates a task without leaked ground truth.
- [ ] All 14 tool schemas are registered and category-fixed.
- [ ] Local and Docker runs return identical CSV events for the same query.
- [ ] Generated retrieval, reasoning, and documentation checkpoints pass on a known-good fixture and fail on intentionally corrupted output.
- [ ] Batch generation reports every processed, exported, rejected, and review-queue case.
