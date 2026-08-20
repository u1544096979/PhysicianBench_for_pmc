# Spec: OncoBench 任务生成流水线 v2（多节点 LLM 决策 + 做题验证）

- **日期**: 2026-08-20
- **状态**: Approved
- **分支**: `feat/task-generation-v2`
- **范围**: 任务生成流水线（阶段3）；不含 agent 评测运行时、不含全量配额分配

---

## 1. 背景与动机

现有 oncology 生成流水线（单次 LLM 自由生成 instruction）存在四个问题：

1. task 类型单一（3 个已生成 task 全是"诊断时点信息复述"，无临床推理）
2. LLM 一次调用同时负责选 target、写 instruction、判断质量，不可控
3. 无题目有效性验证——生成即入库，没有"这道题能不能被解出来"的检验
4. 旧 task 目录 `tasks/oncology-v1/` 质量差，已删除

v2 的核心转变：**从"单次生成"改为"多节点决策流水线"**——每个 LLM 节点职责单一，出题后先做题验证再落盘，不合格打回重出。

## 2. 目标

### 必须达成

- G1: 6 节点 LangGraph 流水线跑通：标注推荐 → 任务生成 → 静态验证 → 做题 → 答案评估 → checkpoint 生成，最后代码清洗落盘
- G2: 4 种 task 类型（T1 分期判定 / T2 疗效评估 / T3 分子标志物解读 / T4 诊断推理），Ground Truth 全部来自病历记录的客观事实
- G3: 做题验证——每道题在入库前由 LLM 模拟 agent 实际解一遍，答案与标签不一致则打回
- G4: checkpoint 4 层结构（数据获取/临床推理/结果判定/文档完整），声明式 JSON 落盘
- G5: 5 个 pilot case 端到端跑通（成功或进 review_queue，不允许崩溃）
- G6: 标注结果持久化，重跑跳过

### 不做（Non-Goals）

- 不做全量 1491 case 的规则配额分配层（pilot 阶段用模型推荐；全量分配层后续迭代）
- 不做 agent 真实评测运行时（复用现有 `scripts/run_task.py` + MiniAgent，本期不改）
- 不做多模型分工（出题/做题/裁判先统一用同一个 LLM 配置，`AGENT_EVAL` 或 `GENERATION` 均可，留分离接口）
- 不做 checkpoint 的代码级评测执行器（本期 checkpoints.json 只落盘 + LLM 裁判层可用；结构化匹配执行器下期做）
- 不承诺 pilot 5 case 全部产出合格任务包——重试用尽说明该轨迹不适合出题，进 review_queue 是合法终态

## 3. 已确认的决策记录

| # | 决策 | 状态 |
|---|---|---|
| D1 | 流水线形态：标注推荐 → 生成 → 静态验证 → 做题 → 答案评估 → checkpoint → 清洗落盘 | ✅ 已确认 |
| D2 | Task 类型用自研 T1-T4（基于轨迹客观事实），不抄 PhysicianBench 原版四类 | ✅ 已确认 |
| D3 | checkpoint 评估框架借鉴 PhysicianBench 4 层结构 | ✅ 已确认 |
| D4 | 全部节点由 LLM 决策，代码只做：加载、分组、清洗、字面防泄漏、落盘 | ✅ 已确认 |
| D5 | ③静态验证、⑤答案评估不通过 → 打回②重新生成，同一 case 重试上限 3 次 | ✅ 已确认 |
| D6 | 重试用尽 → review_queue（"该轨迹可能不适合出题"），不回①换类型 | ✅ 已确认 |
| D7 | 做题节点：一次 LLM 调用，输入=instruction+截断后轨迹全文，输出=答案+推理 | ✅ 已确认 |
| D8 | 答案评估：先只做 LLM 裁判（无规则匹配） | ✅ 已确认 |
| D9 | 标注结果持久化到 `generated/labels/<case_id>.json`，重跑跳过 | ✅ 已确认 |
| D10 | 删除 `tasks/oncology-v1/`，新任务输出 `tasks/oncology-v2/` | ✅ 已已执行 |
| D11 | instruction/输出/数据全中文；LLM 调用的 prompt 也用中文 | ✅ 已确认 |
| D12 | 统一一个 LLM 配置，做题与出题不强制分离模型 | ✅ 已确认 |
| D13 | Pilot 验收：产出任务包不强求，5 case 不崩溃 + review_queue 原因分类清晰即算通过 | ✅ 已确认 |

## 4. Task 类型定义（T1-T4）

### 公共约束

- Ground Truth 必须是**病历中已记录的客观事实**（分期编码/疗效结论/标志物状态/诊断名称），不是"应该怎么做"的主观决策
- 每种类型定义：适用条件（供①标注判断）、instruction 模板（供②填充）、ground_truth 结构（供②提取）
- 模型在②生成时受"分配的类型"约束，不自由跨类型

### T1 分期判定

| 项 | 内容 |
|---|---|
| 适用条件 | 轨迹中存在分期信息事件（临床分期/病理分期/TNM/FIGO 等），且截断前有病理或影像证据 |
| Agent 任务 | 基于截断前的病理+影像+病史证据，判定肿瘤分期 |
| Ground Truth 结构 | `{分期系统, T分期, N分期, M分期, 总分期, 原文分期编码}` |
| 检查点方向 | 是否查病理/影像；是否正确识别原发部位；T/N/M 各字段判定；文档完整性 |

### T2 疗效评估

| 项 | 内容 |
|---|---|
| 适用条件 | 轨迹中存在疗效评估事件（RECIST/CR/PR/SD/PD/缓解/进展等），且截断前有≥2 次可对比的影像/评估记录 |
| Agent 任务 | 基于截断前影像与临床评估记录，按 RECIST 1.1 判断疗效 |
| Ground Truth 结构 | `{疗效结论, 评估依据描述, 靶病灶变化描述}` |
| 检查点方向 | 是否查基线/随访影像；是否识别靶病灶；疗效结论判定；依据陈述；文档完整性 |

### T3 分子标志物解读

| 项 | 内容 |
|---|---|
| 适用条件 | 轨迹中存在分子标志物检测事件（HER2/ER/PR/MMR/MSI/PD-L1/KRAS/EGFR/ALK/ROS1/基因检测等），且截断前有病理背景 |
| Agent 任务 | 解读关键标志物状态及临床意义（用药指导/预后判断） |
| Ground Truth 结构 | `{标志物名称, 检测结果, 检测方法, 临床意义}` |
| 检查点方向 | 是否查病理/免疫组化/基因检测；标志物状态判定；临床意义解读；文档完整性 |

### T4 诊断推理

| 项 | 内容 |
|---|---|
| 适用条件 | 轨迹中存在明确诊断事件，且截断前有多源证据链（病史+影像+病理≥2 类） |
| Agent 任务 | 推断原发肿瘤部位、组织学类型、转移情况 |
| Ground Truth 结构 | `{原发肿瘤, 组织学类型, 转移情况, 诊断名称}` |
| 检查点方向 | 是否查病史/影像/病理；原发部位推断；组织学类型；转移判断；文档完整性 |

## 5. 流水线架构

### 5.1 图结构（LangGraph）

```
                    ┌─────────────────────────────────────────┐
                    │                                         │
                    v                                         │
load_case → build_timeline → [① label_and_recommend]         │
                                │                            │
                                v                            │
                          [② generate_task] ◄──────────┐    │
                                │                      │    │
                                v                      │    │
                          [③ validate_task] ──fail──►│    │
                                │ pass                │    │
                                v                     │    │
                          [④ solve_task] ────────────►│    │
                                │                     │    │
                                v                     │    │
                          [⑤ evaluate_answer] ──fail─►│    │
                                │ pass                │    │
                                v                     │
                          [⑥ generate_checkpoints]    │
                                │                     │
                                v                     │
                          [⑦ materialize_and_persist]│
                                │                     │
                                v                     │
                               END              重试≥3 ──► [review_queue] → END
```

说明：
- ① label_and_recommend：若已有持久化标注则跳过（G6），直接用存好的类型
- ③④⑤ 任一 fail → 打回②；同一 case 打回累计 ≥3 次 → 写入 review_queue，END
- ⑤ 的 fail 必须带原因分类（见 5.4），②重试时携带失败原因上下文

### 5.2 节点职责

| 节点 | 执行者 | 输入 | 输出（写入 state） | 核心约束 |
|---|---|---|---|---|
| load_case | 代码 | case_id | raw_events, data_root | 不可变加载 |
| build_timeline | 代码 | raw_events | event_groups, ordered_events | 按 event_date+`_source_row` 排序，按 group_id 聚合 |
| ① label_and_recommend | LLM | event_groups 摘要 | `label: {suitable_types[], recommended_type, reason}`，持久化 | 只判断"适合哪些类型+推荐哪个"，不生成任务内容；已持久化则跳过 |
| ② generate_task | LLM | recommended_type + event_groups + 失败原因（若有） | `task_draft: {target_group_id, cutoff_date, instruction, ground_truth, task_type}` | 受类型约束选答案组+定截断+写中文 instruction |
| ③ validate_task | LLM | task_draft + 截断前事件 | `validation: {pass, issues[]}`（泄漏/可推理/较唯一三项） | 任一 issue 为 fatal→fail |
| ④ solve_task | LLM | instruction + 截断前轨迹全文 | `solution: {answer, reasoning}` | 一次调用；无工具；不得见到答案组及其后事件 |
| ⑤ evaluate_answer | LLM | solution + ground_truth | `evaluation: {pass, verdict: 一致/不一致/疑似泄漏, reason}` | 先只做 LLM 裁判；"秒答无推理"判疑似泄漏 |
| ⑥ generate_checkpoints | LLM | task_draft + solution（做题轨迹参考） | `checkpoints: Checkpoint[]`（4 层声明式 JSON） | 每层至少 1 条，Data Retrieval 层引用真实存在的 category |
| ⑦ materialize_and_persist | 代码 | task_draft + checkpoints | 任务包目录 | 清洗+字面泄漏检测+结构校验+落盘 |

### 5.3 State 定义

```python
class GenerationState(TypedDict, total=False):
    # 输入
    case_id: str
    data_root: Path
    task_types_config: dict          # T1-T4 定义（含模板）

    # 基础数据（代码生成）
    raw_events: list[dict[str, str]]
    event_groups: list[EventGroup]   # 含 group_id, date, category, events

    # ①标注
    label: LabelResult               # suitable_types, recommended_type, reason

    # ②生成（含重试）
    attempt: int                     # 当前是第几次生成（1-based）
    failure_history: list[FailureRecord]  # 打回原因记录
    task_draft: TaskDraft            # target_group_id, cutoff_date, instruction, ground_truth, task_type

    # ③④⑤验证
    validation: ValidationResult     # pass, issues[]
    solution: SolutionResult         # answer, reasoning
    evaluation: EvaluationResult     # pass, verdict, reason

    # ⑥checkpoint
    checkpoints: list[Checkpoint]

    # 终态
    status: str                      # "persisted" | "review_queue"
    review_reason: str               # 进队列的原因分类
    task_dir: Path                   # 产出目录（persisted 时）
```

### 5.4 打回与重试协议

| 来源 | fail 原因分类 | 打回到 | 携带上下文 |
|---|---|---|---|
| ③ validate | `泄漏` / `不可推理` / `不唯一` | ② | issues 列表 |
| ⑤ evaluate | `答案不一致` / `疑似泄漏(秒答)` | ② | verdict + reason |
| ④ solve 异常 | `做题失败`（LLM 输出不可解析等） | ② | 异常摘要 |
| 重试≥3 | `轨迹不适合出题` | review_queue | 全部 failure_history |

②重试生成时，prompt 中注入 failure_history（"上次因 X 失败，请避免"），并要求换答案事件组或调整截断点。

### 5.5 Checkpoint 声明式 Schema（v1）

```jsonc
// generated/v2/<case_id>/checkpoints.json
{
  "task_type": "T1_staging",
  "checkpoints": [
    {
      "id": "cp1_data_pathology",
      "layer": "data_retrieval",        // data_retrieval | clinical_reasoning | outcome_check | documentation
      "description": "agent 查询了病理类事件",
      "eval_method": "category_query",   // category_query | llm_judge | field_match | llm_judge
      "target": { "category": "病理" },  // eval_method 的参数
      "weight": 1.0
    },
    {
      "id": "cp2_reasoning_primary",
      "layer": "clinical_reasoning",
      "description": "正确识别原发肿瘤部位",
      "eval_method": "llm_judge",
      "target": { "rubric": "输出中明确指出原发肿瘤为宫颈癌（或等同表述）" },
      "weight": 1.0
    },
    {
      "id": "cp3_outcome_T",
      "layer": "outcome_check",
      "description": "T 分期判定正确",
      "eval_method": "field_match",
      "target": { "field": "T分期", "expected": "T2", "source": "ground_truth" },
      "weight": 1.0
    }
  ]
}
```

四层与 eval_method 的对应：

| layer | eval_method | 执行者 |
|---|---|---|
| data_retrieval | `category_query` | 代码（检索 agent trajectory 中的工具调用记录） |
| clinical_reasoning | `llm_judge` | LLM（rubric 裁判） |
| outcome_check | `field_match` | 代码（结构化字段匹配，**本期仅落盘不执行**） |
| documentation | `llm_judge` | LLM（rubric 裁判） |

约束：
- 每个 task 生成 4-8 条 checkpoint，四层各≥1 条
- data_retrieval 层的 `target.category` 必须引用该 case 截断前真实存在的 category（代码校验）
- outcome_check 层的 expected 值必须与 ground_truth 一致（代码校验）

### 5.6 产物目录结构

```
tasks/oncology-v2/<case_id>/
├── instruction.md            # 中文任务指令（含评估时点/角色/交付物结构）
├── ground_truth.json         # T1-T4 对应结构 + target_group_id + cutoff_date
├── checkpoints.json          # 5.5 schema
├── task.toml                 # 元信息（case_id, task_type, 生成时间, model, attempt 数）
└── data/
    └── cleaned_trajectory.csv  # 截断清洗后的轨迹（agent 可见）

generated/
├── labels/<case_id>.json     # ①标注结果（持久化，重跑跳过）
└── v2/<case_id>/
    ├── solution.json         # ④做题原始输出
    └── review_queue.jsonl    # 追加：终态失败的 case 及原因
```

### 5.7 防泄漏约束（贯穿）

1. ④做题输入只含截断前事件（代码裁剪，④节点拿不到答案组及其后任何事件）
2. ③静态验证含字面泄漏检测（代码：instruction 与 ground_truth 值的字符串包含检查）+ LLM 语义泄漏判断
3. ⑦落盘前再次字面检测 cleaned_trajectory.csv 与 instruction（防清洗逻辑失误）
4. ⑤评估可判"疑似泄漏"（秒答且无推理）触发打回

### 5.8 LLM 配置（本期简化）

- 统一一个 LLM：复用现有 `pipeline/llm.py` 客户端与 `GENERATION_*` 环境变量；未配置时回退 `AGENT_EVAL_*`
- 全部 prompt 用中文（D11）
- 所有 LLM 节点输出要求 JSON（prompt 中给出 schema + few-shot 示例），解析失败按一次软重试，再失败记 `做题失败`/`生成失败` 走打回协议
- 每节点调用记录到 `generated/v2/<case_id>/trace.log`（时间/节点/prompt 版本/token 数），便于审计

## 6. 验收标准（Pilot：5 个 case）

| # | 标准 | 通过条件 |
|---|---|---|
| A1 | 流水线稳定性 | 5/5 case 走到终态（persisted 或 review_queue），无未捕获异常 |
| A2 | 任务包产出 | 不强求数量；每个 persisted 任务包含 instruction.md + ground_truth.json + checkpoints.json + cleaned_trajectory.csv + task.toml，且通过字面泄漏检测 |
| A3 | checkpoint 质量 | persisted 任务的 checkpoints.json：4-8 条、四层齐全、data_retrieval 引用真实 category、outcome_check 与 ground_truth 一致（代码校验通过） |
| A4 | review_queue 可读 | review_queue.jsonl 每条含 case_id + 原因分类 + failure_history 摘要 |
| A5 | 单元测试 | 新增节点逻辑的测试全绿；现有测试套件不回归（pipeline 测试需适配新 graph 后修复） |
| A6 | 人工抽查 | 逐条阅读 pilot 任务的 instruction + ground_truth，无事实性错误（人工执行） |

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| 做题模型过强，秒答导致误判泄漏 | ⑤裁判 prompt 明确"有推理过程即不算秒答"；pilot 人工复核 verdict 分布 |
| 标签不唯一场景多（如多处分期记录） | ②prompt 要求优先选证据链最完整的首次明确记录；③专项检查"较唯一" |
| 单 LLM 全流程导致裁判偏置 | 本期接受（D12）；trace.log 留证，下期分离 SOLVER/JUDGE 配置 |
| LLM 输出 JSON 解析失败率高 | prompt 内嵌 schema + few-shot；软重试 1 次；失败走打回 |
| 全量跑时 token 成本失控 | pilot 结束后统计 trace.log 平均 token，评估全量成本再决策 |

## 8. 后续迭代方向（不在本期）

- 全量 1491 的配额分配层（标注矩阵 → 癌种×类型配额 → 定向生成）
- SOLVER/JUDGE/GENERATOR 三模型分离配置
- checkpoint 执行器（field_match 代码执行 + category_query 轨迹检索）
- agent 真实评测 + pass@k 指标
- 基于 review_queue 的人工审核界面
