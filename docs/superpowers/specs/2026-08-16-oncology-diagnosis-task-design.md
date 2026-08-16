# Oncology 诊断任务生成设计

## 目标

基于固定的 5 个 oncology CSV `case_id`，从每个完整病例中生成一个可运行的诊断任务。LangGraph 负责编排当前固定的任务生成流水线；任务生成阶段由大模型选择一个诊断性临床事件组，并由程序生成该事件之前的清洗数据；模型运行评测阶段复用现有 Agent、CSV 工具和 trajectory 框架，在本地完成诊断任务。

固定 pilot case：

- `71af50c891bd0e80cd017c8beb2bb446`
- `15c35bb60e48e62f9beb9fd127248e03`
- `7df4bd9af484dcec897b2f2726e01db2`
- `01864b911256ca7332f7974165d7aeb8`
- `aca554ac1716cf2fb7e2b94d80590e52`

## 核心定义

任务答案不是单行 CSV 记录，而是一个完整的 `group_id` 事件组。事件组内的多行字段共同构成诊断答案，例如诊断名称、分期、TNM 信息和诊断依据。

目标事件不要求 `category` 必须等于“诊断”。任务生成模型可以选择 `诊断名称`、`病理诊断`、`出院诊断` 或其他 `feature_name/value` 中包含明确诊断结论的事件组。

任务生成模型可以查看完整病例；被评测的 Agent 只能查询清洗后的病例数据。

## 两阶段模型环境

当前只配置两个独立的模型环境，不引入任务类型路由或复杂的 environment profile：

```text
generation_env
  └── 任务生成阶段使用

agent_eval_env
  └── Agent 运行评测阶段使用
```

每个环境可以独立配置模型名称、API key、环境变量和其他 key-value 参数。任务生成模型与被评测 Agent 可以使用不同模型、不同服务商或不同运行参数。

环境配置只负责为对应阶段提供运行参数，不改变任务生成图的节点结构，也不让任务生成阶段执行 Agent 评测。

## 阶段一：任务生成

该阶段使用 `generation_env` 中配置的模型和环境变量。

流水线：

```text
load_case
  -> build_timeline
  -> select_target_and_draft_task
  -> materialize_cleaned_case
  -> validate
  -> export_task
```

### `load_case`

读取一个完整的原始病例 CSV。原始数据只读，不在此阶段修改。

### `build_timeline`

按照 CSV 原始行顺序构建事件时间线，并将相同 `group_id` 的行聚合为一个事件组。事件组的先后顺序由该组首次出现的原始行确定；这也用于处理同一天存在多个事件组的情况。

### `select_target_and_draft_task`

大模型接收完整病例和任务目标，输出结构化结果：

```json
{
  "target_group_id": "...",
  "target_event_date": "2021-11-21",
  "target_category": "病理",
  "selection_rationale": "...",
  "role": "肿瘤科医生",
  "instruction": "...",
  "deliverable": "给出最终诊断及简要依据"
}
```

模型必须选择一个真实存在的诊断性事件组，并返回足以定位该事件组的 `group_id`。任务提示词只能描述任务目标、角色、可用数据和输出要求，不能直接写出目标事件的 `value`、ground truth 或 evaluator 字段。

### `materialize_cleaned_case`

程序从原始 CSV 复制出一个独立清洗文件：

```text
可见数据：目标事件组之前的所有事件组
隐藏数据：目标事件组本身及之后的所有事件组
```

目标事件组内的所有行都隐藏，不能只删除某一行。对于同一天的其他事件组，按照原始 CSV 中首次出现的行顺序判断其是否位于目标事件组之前或之后。

原始 CSV 永远不被删除或覆盖。清洗结果单独保存到：

```text
data/oncology_complete_trajectory/cleaned/<case_id>.csv
```

### `validate`

确定性校验至少包括：

- `target_group_id` 在原始病例中存在；
- 目标事件组的全部字段可以从原始数据重建；
- 清洗数据不包含目标事件组；
- 清洗数据不包含目标事件组之后的事件组；
- 任务提示词不包含目标诊断值；
- 任务引用的工具名称合法；
- 每个 pilot case 只导出一个任务。

如果模型选择的事件组不存在、没有明确诊断意义或无法形成足够的前置临床信息，则任务进入人工复核/重生成队列，不直接导出。

## 文件契约

任务定义与清洗病例数据分离：

```text
tasks/oncology-v1/<case_id>/
├── instruction.md
├── task.toml
├── ground_truth.json
└── tests/
    └── test_outputs.py

data/oncology_complete_trajectory/
├── raw/csv/<case_id>.csv
├── cleaned/<case_id>.csv
├── generated/<case_id>/
└── index/
```

`ground_truth.json` 保存目标事件组的完整字段和来源引用，只供评测器使用，不注册给 Agent。工具运行时通过 `case_id` 查找 `cleaned/<case_id>.csv`。

## 阶段二：模型运行评测

阶段二不再启动 Docker 或 FHIR 服务，直接在本地运行：

该阶段使用 `agent_eval_env` 中配置的模型和环境变量。

```text
加载 task
  -> 注册 CSV 查询工具
  -> 将工具 data_root 指向 cleaned/
  -> Agent 查询并输出诊断
  -> 保存 trajectory/workspace/logs
  -> 规则评估和 LLM judge
```

现有 Agent loop、function-calling、CSV 工具和 trajectory 机制继续复用。运行器需要移除 FHIR/Docker 生命周期，并保证 Agent 工具只访问清洗数据目录。

规则评估和 LLM judge 属于阶段二，不属于任务生成流水线。任务生成阶段只输出 ground truth、来源引用和任务要求；阶段二再将 Agent 输出与隐藏答案进行比较。

## 测试边界

第一阶段的测试覆盖：

- 5 个固定 `case_id` 都能定位；
- 每个病例都能生成一个目标事件组；
- 清洗结果符合事件组边界；
- Agent 工具不会读取原始或隐藏数据；
- 任务文件结构与现有 `tasks/v1` 风格一致。

第二阶段的测试覆盖：

- 本地 Agent 可以正常调用 CSV 工具；
- trajectory 和 workspace 正常生成；
- Agent 输出可以进入规则评估和 LLM judge；
- 评测失败能区分数据查询、诊断输出和评估环节。

本设计不包含汇报页面、批量 1491 case 处理和 FHIR 兼容层；这些属于后续工作。
