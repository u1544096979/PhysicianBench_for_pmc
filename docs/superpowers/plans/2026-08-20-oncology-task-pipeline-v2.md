# Implementation Plan: OncoBench 任务生成流水线 v2

- **Spec**: `docs/superpowers/specs/2026-08-20-oncology-task-pipeline-v2.md`
- **日期**: 2026-08-20
- **分支**: `feat/task-generation-v2`
- **原则**: 破坏性重写 pipeline/oncology_generation/，git 可回溯；tests 同步重写

---

## Task 1: 清理旧实现 + 新 schemas

**改动文件**:
- 删除: `pipeline/oncology_generation/nodes.py`（旧单节点版）
- 重写: `pipeline/oncology_generation/schemas.py`

**内容**:
1. `GenerationState`（见 spec 5.3）
2. 数据类：`LabelResult / TaskDraft / ValidationResult / SolutionResult / EvaluationResult / Checkpoint / FailureRecord`
3. `TaskDraft` 含 `task_type: Literal["T1_staging","T2_response","T3_biomarker","T4_diagnosis"]`
4. `EventGroup` 保留（group_id/date/category/events），从旧 schemas 迁移

**测试**: `tests/test_v2_schemas.py` — 数据类构造、默认值、Literal 校验

## Task 2: task_types 配置

**新增文件**: `pipeline/oncology_generation/task_types.py`

**内容**:
1. `TASK_TYPES: dict[str, TaskTypeDef]`，每类含：
   - `label`: 中文名（分期判定/疗效评估/分子标志物解读/诊断推理）
   - `applicability`: 适用条件描述（给①标注用）
   - `instruction_template`: 中文模板，占位符 `{cutoff_date}`（含角色/评估时点/任务/交付物结构化字段要求）
   - `ground_truth_fields`: 字段列表（如 T1: 分期系统/T/N/M/总分期/原文编码）
   - `checkpoint_hints`: 每层 checkpoint 的设计提示（给⑥用）
2. 四类模板按 spec §4 编写，instruction 交付物统一要求"保存为 output/diagnosis_report.md + 结构化字段"

**测试**: `tests/test_v2_task_types.py` — 四类配置完整、模板占位符可填充

## Task 3: prompts v2（全中文）

**重写文件**: `pipeline/oncology_generation/prompts.py`

**内容**: 6 个节点的中文 prompt 函数，全部要求 JSON 输出（内嵌 schema+示例）：
1. `build_label_prompt(event_groups_summary)` — ①标注：输出 `{suitable_types, recommended_type, reason}`
2. `build_generate_prompt(task_type_def, event_groups, failure_history)` — ②生成：输出 `{target_group_id, cutoff_date, instruction, ground_truth}`；注入失败原因
3. `build_validate_prompt(task_draft, pre_cutoff_events)` — ③验证：输出 `{pass, issues:[{type: 泄漏|不可推理|不唯一, detail}]}`
4. `build_solve_prompt(instruction, pre_cutoff_events)` — ④做题：输出 `{answer, reasoning}`；明确"仅基于给定轨迹"
5. `build_evaluate_prompt(solution, ground_truth)` — ⑤评估：输出 `{pass, verdict: 一致|不一致|疑似泄漏, reason}`；含"有推理过程不算秒答"规则
6. `build_checkpoint_prompt(task_draft, task_type_def, solution)` — ⑥checkpoint：输出 checkpoints 数组（spec 5.5 schema）

**测试**: `tests/test_v2_prompts.py` — 每个函数包含关键约束文本、JSON schema 说明

## Task 4: 重写 graph + 代码节点

**改动文件**:
- 重写: `pipeline/oncology_generation/graph.py`
- 新增: `pipeline/oncology_generation/nodes.py`（v2 版）

**nodes.py 内容**:
```
load_case(event_store) → raw_events
build_timeline() → event_groups
label_and_recommend() → 读 generated/labels/<case_id>.json，无则调 LLM 并持久化
generate_task() → task_draft（LLM）
validate_task() → validation（LLM + 代码字面泄漏预检）
solve_task() → solution（LLM；代码裁剪截断前事件）
evaluate_answer() → evaluation（LLM 裁判）
generate_checkpoints() → checkpoints（LLM + 代码校验）
materialize_and_persist() → 清洗 CSV + 双重字面泄漏检测 + 落盘任务包
```

**graph.py 内容**:
```
START → load_case → build_timeline → label_and_recommend → generate_task
generate_task → validate_task
validate_task ──(fail & attempt<3)──→ generate_task
validate_task ──(pass)──→ solve_task
solve_task ──(异常/解析失败)──→ [按失败处理: attempt+1 → generate_task 或 review_queue]
solve_task ──(ok)──→ evaluate_answer
evaluate_answer ──(fail & attempt<3)──→ generate_task
evaluate_answer ──(pass)──→ generate_checkpoints
generate_checkpoints → materialize_and_persist → END
任一环节 attempt≥3 → review_queue 节点（写 jsonl）→ END
```

路由函数：`route_after_validation / route_after_solve / route_after_evaluation`，读 `state.attempt` 与各 pass 标志。

**review_queue 节点**: 追加写 `generated/v2/review_queue.jsonl`，含 case_id、终态原因、failure_history 摘要。

**trace.log**: 每个 LLM 节点包装器统一记录（节点名/时间/token/耗时）。

**测试**: `tests/test_v2_graph.py` — 用 fake LLM（monkeypatch）验证：正常通过路径、③fail 打回、⑤fail 打回、attempt≥3 进 review_queue、标注缓存命中跳过 LLM

## Task 5: 入口脚本

**新增文件**: `scripts/generate_oncology_v2.py`

**内容**:
```
用法: python -m scripts.generate_oncology_v2 --cases <case_id>... | --pilot 5 | --all
选项: --relabel（强制重标注）--output-root tasks/oncology-v2 --data-root data/oncology_complete_trajectory/raw/csv
流程: 选 case → 逐个编译 graph → invoke → 汇总打印（persisted/review_queue 统计 + 任务包路径）
```

pilot case 选择：复用 `data/oncology_complete_trajectory/raw/csv/` 前 5 个文件（与旧 pilot 一致）。

**测试**: `tests/test_v2_cli.py` — 参数解析、case 选择逻辑（--pilot/--cases）

## Task 6: 集成测试 + pilot 试跑

**内容**:
1. `tests/test_v2_integration.py` — fake LLM 下全流程：断言产物目录结构、checkpoints.json 校验规则（四层齐全/data_retrieval 引用真实 category/outcome_check 与 ground_truth 一致）、review_queue 格式
2. 真实 LLM pilot：`--pilot 5`，检查 A1-A5 验收标准
3. 修复回归的旧测试（引用旧 nodes/graph 的测试适配或删除）
4. 人工抽查 A6（用户执行）

**完成标志**: spec §6 验收表 A1-A5 全绿

## 执行顺序与依赖

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6
（1/2/3 相互独立可并行，4 依赖 1+2+3，5 依赖 4，6 依赖全部）
```

## 明确不做

- 不改 `agent/`、`scripts/run_task.py`、`tools/`（评测运行时不动）
- 不做多模型配置
- 不做 checkpoint 执行器
- 不删 `tasks/v1/`（原版 PhysicianBench 示例，保留参考）
