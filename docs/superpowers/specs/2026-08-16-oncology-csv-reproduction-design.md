# Oncology CSV 复现改造设计

## 目标

将 `pmc_case_data_audit` 的 oncology complete trajectory CSV 数据接入 PhysicianBench 的 Agent、任务和 checkpoint 评测骨架。第一阶段先完成一个 case 的端到端运行，随后使用同一套契约批量生成并运行全部 case。

当前仓库是 CSV 专用复现副本，原始 PhysicianBench 保留在另一份独立克隆中。本改造不要求继续兼容 FHIR，也不保留双后端运行模式。

## 数据布局

- `data/oncology_complete_trajectory/raw/csv/`：原始 CSV，按 `case_id` 文件保存。初期通过软链接接入现有数据目录，避免复制和误提交原始数据。
- `data/oncology_complete_trajectory/index/`：按 case 的轻量索引和 manifest，不修改原始 CSV。
- `data/oncology_complete_trajectory/generated/`：LangGraph 生成过程的中间状态、候选轨迹和复核结果。
- `tasks/oncology-v1/<task_id>/`：通过复核后导出的任务、checkpoint 和 ground truth。

CSV 的核心事件字段为 `case_id`、`encnt_no`、`group_id`、`subject`、`feature_name`、`feature_type`、`value`、`actual_value`、`unit`、`event_date`、`category`。原始字段必须可追溯，不在数据层做 LLM 总结。

## CSV 查询工具

保留现有 `ToolRegistry` 和 Agent function-calling 机制，将原 FHIR 查询工具替换为 14 个固定 category 的 CSV 查询工具：入院、病史、诊断、检验、影像、病理、手术、用药、病程、评估、不良反应、出院、会诊、其他。每个工具由统一底层查询函数实现，只固定自身 category；另保留文件写入工具。

工具统一接受 `case_id`，并支持可选的 `subject`、`feature_name`、`event_date`、`group_id` 和 `limit` 过滤。返回原始事件对象，至少包含 `case_id`、`category`、`event_date`、`group_id`、`subject`、`feature_name`、`value`、`actual_value`、`unit` 和 `feature_type`。

第一版只做 category 查询和轻量字段过滤。第二版可为每类事件增加展示配置，例如检验展示项目、数值和单位，影像展示检查主体及所见/结论，用药展示药品、剂量和方案；配置只改善展示，不改变原始真值。

## LangGraph 任务生成

任务生成图的状态包括 `case_id`、`raw_events`、`candidate_segments`、`selected_segment`、`task_draft`、`checkpoint_drafts`、`validation_errors` 和 `review_status`。

节点顺序：

`load_case -> build_timeline -> select_anchor -> draft_task -> draft_checkpoints -> validate -> review -> export`

- `load_case` 读取单个 case。
- `build_timeline` 按 `event_date`、`encnt_no` 和 `group_id` 组织事件。
- `select_anchor` 让模型从真实时间线选择任务锚点，并返回日期、group_id 和事件行引用。
- `draft_task` 基于锚点前后事件生成任务提示词、身份和交付物。
- `draft_checkpoints` 生成 3-6 个 checkpoint，每个必须包含目标行为、依赖 category/tool、原始事件引用、验证方式和通过标准。
- `validate` 做确定性检查：引用存在、真值存在、工具合法、任务没有泄漏答案。
- `review` 由第二次模型调用或人工复核；失败时回到对应草稿节点重试。
- `export` 输出现有任务目录所需的 `task.toml`、`instruction.md`、测试文件和不可变 `ground_truth.json`。

第一版 checkpoint 只支持 retrieval、reasoning 和 documentation 三类。只有 CSV 中存在明确动作事件时，才增加 action checkpoint。

## 运行与验收

运行器改成 CSV 专用流程：加载指定 case 和任务，注册 CSV 工具，运行 Agent，保存 trajectory/workspace/logs，并执行 pytest checkpoint。原 FHIR 容器启动逻辑不再是运行主链路。数据根目录默认使用项目内标准路径，同时提供可选 `--data-root` 以支持换机器或 Docker 只读挂载。

单 case 验收标准：

1. 生成一个可审阅的任务目录和 ground truth。
2. Agent 成功调用至少两类 CSV 查询工具。
3. 产出任务要求的结果文件。
4. retrieval、reasoning、documentation 三类 checkpoint 可由 pytest 稳定判定。
5. 同一输入重复运行的工具查询结果一致。

单 case 契约稳定后，再批量处理全部 CSV；生成失败或复核不通过的 case 进入 review 队列，不阻塞其他 case。
