# Oncology v2 任务噪声注入设计

日期：2026-08-20
状态：已评审（brainstorming 通过），待实现

## 1. 背景与目标

当前 v2 任务的 `cleaned_trajectory.csv` 通常只有 10~50 行，且每行大多与任务强相关。
Agent 约 8 次工具调用即可拿到关键证据并给出正确答案，检索/筛选难度不足。

**目标**：向任务数据中注入大量"事实无关但真实/真实感"的噪声事件，让关键证据被埋入
更多数据中，提升检索/筛选难度，同时保证 ground truth 仍然唯一可推导。

**核心红线（用户明确要求）**：
- 禁止 B 类矛盾/误导证据（任何可能与答案证据矛盾、改变推理轨迹的干扰）
- 禁止使用其他病例的真实行作噪声（1491 例均为肿瘤病例，跨病例行会引入肿瘤相关干扰）
- 噪声必须"事实无关"，不是"与答案矛盾"

## 2. 范围

**In scope**
- 新增独立包 `pipeline/noise_injection/`（噪声核心引擎）
- v2 生成流水线插入 `inject_noise` 节点（管新生成的任务）
- 新增 `scripts/apply_noise.py` 批处理脚本（管存量 991 个 v2 任务）
- 存量任务加噪产物写入平行目录 `tasks/oncology-v2-noisy/<case_id>/`，原 v2 目录不动

**Out of scope / 暂缓**
- 共病线叙事（既往史+共病诊断+慢性病长期用药）——本版本不做，架构上留扩展位
- 影像/病理/手术/入院/出院/其他/会诊类别的噪声——整类禁用（见 §4.2）
- v1 任务——不动
- Agent 工具层、checkpoint、指令模板——均不改动；**指令中不提示存在噪声**
  （真实 EHR 本就不提示，这本身是难度来源之一）

## 3. 噪声内容规格

### 3.1 两层结构

**Layer A：独立常规行（默认 ~60 行/任务，`noise_rows` 参数可控）**

| 类别 | 允许的 feature_name | 内容规则 |
|---|---|---|
| 评估 | 血压 / 心率 / 体温 / 呼吸 / 查体 | 生命体征在正常范围或正常低值/高值边缘；查体为非肿瘤描述（"心律齐、腹软无压痛、双下肢无水肿"等） |
| 检验 | 检验项目 + 具体项目（血常规四件套、肝肾功、血糖、电解质、CRP 等） | 数值正常或轻度异常；**肿瘤标志物全禁** |
| 用药 | 药品名称 + 剂量 + 给药途径（+ 用药周期） | 只许支持治疗药：护胃（奥美拉唑等）、抗凝（依诺肝素等）、维生素、补液、缓泻剂；**抗肿瘤药全禁** |
| 病程 | 病程 / 症状（轻微） | 泛化记录（"一般情况可，饮食睡眠良好，大小便正常"）；治疗反应/随访结果/PFS/OS/周期数禁用 |

**Layer B：急性病程线（默认 2 条/任务，`episodes` 参数可控）**

每条为一个自包含小叙事包（2~4 天），由一次 LLM 调用整体生成、日期链自洽：

```
示例：低热小病程
  病程   D0  "今日患者体温 38.2°C，伴畏寒、纳差"
  评估   D0  体温 38.2°C
  用药   D0  对乙酰氨基酚 0.5g 口服
  病程   D1  "体温恢复正常，食欲改善"
```

允许出现的药品为普通疾病用药（感冒/低热：对乙酰氨基酚、布洛芬、阿莫西林、复方感冒药）。
叙事包内所有行仍落在 §3.1 的 4 个允许类别内。

### 3.2 整类禁用（红线，写入 catalog + 规则闸门双重保障）

| 类别 | 禁用原因 |
|---|---|
| 影像 | 分期/疗效核心证据，任何新增影像都是 B 类矛盾风险 |
| 病理 | 病理诊断/免疫组化/分子标志物是 T1/T3 核心 |
| 手术 | 加任何手术都会与分期/治疗线矛盾 |
| 入院 / 出院 | 一 case 一 encnt，重复入院自相矛盾；出院诊断泄露答案且时点常在 target_date 之后 |
| 其他 / 会诊 | 分布太杂 / 全量仅 50 行，性价比低 |
| 诊断 | 其安全内容（良性共病）依赖共病线叙事，本版本未启用；独立加共病诊断行易与"否认高血压糖尿病史"类既有行矛盾 |
| 病史 | 同上，独立既往史行与既有主诉/既往史易重复或矛盾 |
| 不良反应 | 指向特定药物的 AE（手足综合征→卡培他滨类）会与真实用药矛盾 |

**跨类别红线（任何噪声行均不得出现）**：
- 肿瘤标志物：CEA / AFP / CA125 / CA19-9 / CA15-3 / CA72-4 / PSA / CYFRA21-1 / NSE / SCC / LDH 等（完整清单在 `catalog.py` 数据化维护）
- 抗肿瘤药物：一切化疗药、TKI（-tinib）、免疫检查点抑制剂（PD-1/PD-L1/CTLA-4）、内分泌治疗药（T2 的"评估时点前主要治疗"是答案组成部分）
- 疗效/分期相关：疗效评估（CR/PR/SD/PD）、治疗反应、临床/病理分期、TNM、ECOG
- 与病例既有事实冲突的陈述（提示词注入病例关键事实 + 规则层否认模式扫描 + judge 兜底）

### 3.3 时间规则

1. 所有噪声 `event_date ∈ [病例首个事件日期, target_date)`，严格早于评估时点；
   病例首个事件日期 = 该病例原始 CSV（`raw/csv/<case_id>.csv`）中最早的 event_date
2. 生命体征：按住院期逐日分布（真实病历节奏）
3. 常规检验：成簇出现（入院时一簇、治疗中期一簇、评估前一周左右一簇），不做均匀撒点
4. 急性病程线：2~4 天自包含小簇，置于时间窗中段，**避开关键证据事件所在日期**
   （关键证据日 = 目标组 + 可见集合中含肿瘤标志物的检验组 + 影像组的 event_date）
5. 叙事包内日期链自洽（发热日 → 给药日 → 恢复日依次 +1~2 天）

### 3.4 身份与字段一致性

- `case_id` / `encnt_no` = 目标病例
- `group_id` = 每行噪声一个新 UUID（噪声行自成一组，不与真实组混用；
  叙事包的行关联只记录在 manifest 的 `episode_id`，不用 group_id 串联）
- `subject` / `method` / `source` / `_record_source` / `pipeline_version`：
  由 `materialize.py` 从**该病例自身同类别既有行**中采样惯例值（如检验→"血液/血清"，
  用药→"患者"），保证风格与病例一致；若该病例缺少某类别的既有行，
  回退到全量语料中该类别的高频默认值（`catalog.py` 维护）
- `feature_type` 取值遵循 schema 枚举（数值/类别/文本/日期/偏离）；数值行必须 unit 齐全、value 可解析
- **CSV 内不打任何噪声标记**（Agent 渲染可见的列不得泄露噪声身份；审计只靠 manifest）

## 4. 生成与验证流程

```
读病例事实 + 任务上下文（target_date / GT / 关键证据日期 / 既有事实）
  → plan.py      LLM 生成噪声计划（Layer A 行 + 2 条叙事包，JSON）
  → materialize  计划 → 17 字段完整 CSV 行（含 §3.4 一致性规则）
  → 闸门1 safety 规则检查（零 LLM 成本）
  → 闸门2 judge  LLM 逐行裁判
  → 闸门3 solvable 可解性复验
  → 全部通过 → 放行；否则按 §4.3 重试阶梯
```

### 4.1 三道闸门

**闸门 1 规则检查（`safety.py`，零成本）**
- 类别白名单：只允许 评估/检验/用药/病程
- feature_name 黑名单 + 肿瘤标志物清单 + 抗肿瘤药清单扫描
- 日期窗口（§3.3-1）、关键证据日回避（§3.3-4）、叙事包日期链自洽
- schema 合法性：17 字段齐全、feature_type 枚举、数值行 unit/value
- 否认模式规则扫描：病例病史中"否认 X 史"提取后，噪声不得含 X（judge 兜底一般性矛盾）
- **字面泄漏**：噪声行纳入 visible 后重跑现有 `leakage.find_leaked_target_values`

**闸门 2 LLM 裁判（`judge.py`）**
- 输入：GT + 病例关键事实 + 每批 10 行噪声；输出每行 JSON 判定
  `{row, related_to_answer: bool, contradicts: bool, reason}`
- `related_to_answer` 或 `contradicts` 为 true → 该行剔除（重生成一次，再失败则丢弃）

**闸门 3 可解性复验（`solvable.py`）**
- 复用现有 `prompts_v2.build_solve_prompt` / `build_evaluate_prompt`：
  在"干净 visible 事件 + 全部噪声行（同一渲染格式）"上让生成模型完整求解
- 通过条件：evaluate `verdict == "valid"`（即答案与 GT 一致且有推理）
- 这是"加噪后答案仍唯一可推导"的最终兜底

### 4.2 重试阶梯与降级

| 尝试 | 参数 |
|---|---|
| 1 | 全量：`noise_rows=60, episodes=2` |
| 2 | 减量：`noise_rows=30, episodes=1`（重新 plan） |
| 3 | 减量：`noise_rows=30, episodes=1`（重新 plan） |
| 仍失败 | **降级为无噪声**：任务照常落盘（干净版），`final_status="degraded_clean"`，写 review_queue |

任何一次尝试中若闸门 3 失败，记录失败原因（judge 解释 / solver 答案偏差）进 manifest 的
`attempts` 与 review_queue（`reason_class="noise_gate_failed"`），复用现有
`generated/v2/review_queue.jsonl` 追加机制。

## 5. 代码架构

### 5.1 核心包 `pipeline/noise_injection/`（9 个文件，职责单一）

```
pipeline/noise_injection/
├── __init__.py
├── config.py      # NoiseConfig dataclass：全部参数一处集中（见 §7）
├── catalog.py     # 声明式类别目录表：每类允许的 feature_name、取值规则、
│                  #   肿瘤标志物清单、抗肿瘤药清单、禁用类别——review 看这一张表即可
├── prompts.py     # 全部噪声提示词（带版本号 PROMPT_VERSIONS，改词有迹可循）
├── plan.py        # NoisePlanner：病例事实 + 任务上下文 → 噪声计划 JSON
├── materialize.py # 计划 → 17 字段 CSV 行（group_id/日期/subject 惯例采样，§3.4）
├── safety.py      # 闸门 1 规则检查
├── judge.py       # 闸门 2 LLM 逐行裁判（批量 10 行/次）
├── solvable.py    # 闸门 3 可解性复验（复用 prompts_v2 的 solve/evaluate builder）
└── manifest.py    # noise_manifest.json 读写（schema 见 §6.2）
```

依赖方向：`plan/materialize` 依赖 `catalog`；三道闸门互不依赖、可独立单测；
包内不依赖 `oncology_generation` 的 graph/state，仅复用其 `prompts_v2` 与 `leakage` 的纯函数。

### 5.2 入口 1：v2 流水线节点

- `GenerationState` 新增两个字段：`noise_rows: list[dict] | None`、`noise_manifest: dict | None`
- `graph.py`：`evaluate_solution`（valid 分支）→ **`inject_noise`** → `generate_checkpoints`
- `nodes.py` 新增薄节点 `inject_noise`：调用核心包 `run_injection(...)`（内部含重试阶梯 §4.2），
  结果写入 state；节点本身不写业务逻辑
- `materialize` 节点：清洗落盘后，若 `state["noise_rows"]` 非空则追加噪声行到
  `cleaned_trajectory.csv`，并写 `noise_manifest.json`；
  节点内现有"最终字面泄漏检查"（spec D11 兜底）**同时覆盖噪声行**

### 5.3 入口 2：存量任务脚本 `scripts/apply_noise.py`

- 遍历 `tasks/oncology-v2/` 全部任务目录，逐个：
  读 `task.toml` / `ground_truth.json` / `cleaned_trajectory.csv`，
  **并从原始病例 CSV（`data/oncology_complete_trajectory/raw/csv/<case_id>.csv`）提取病例事实与关键证据日期**
  （cleaned CSV 中目标组答案行已被隐藏，关键证据日期必须以原始 CSV 的分组为准）
  → 调同一核心 `run_injection(...)` → 产物写入 `tasks/oncology-v2-noisy/<case_id>/`
- CLI：`--dry-run`（只跑闸门不写盘）、`--resume`（跳过已完成的 case）、
  `--limit N`、`--case-ids a,b,c`、`--workers 1`（默认串行，避免 API 限流）
- 单任务失败不中断批次；结束输出汇总报告（成功/降级/失败计数 + 明细 jsonl）
- LLM client 复用 `llm.client.get_default_client(trace_dir)`

### 5.4 产物布局

```
tasks/oncology-v2-noisy/<case_id>/
├── instruction.md          # 原样复制，不改动
├── task.toml               # 原样复制（data_file 仍为 cleaned_trajectory.csv）
├── ground_truth.json       # 原样复制
├── checkpoints.json        # 原样复制
├── cleaned_trajectory.csv  # 原行 + 追加通过的噪声行
└── noise_manifest.json     # 新增（§6.2）
# 注意：不复制 runs/（旧 runs 基于无噪数据，归属原目录）
```

## 6. 溯源与审计

### 6.1 原则

- 噪声身份只存在于 `noise_manifest.json`，CSV 内不可见（Agent 渲染列均无标记）
- 支持事后分析"Agent 是否查询/引用了噪声行"（manifest 提供 csv_row ↔ 噪声行映射）

### 6.2 `noise_manifest.json` schema

```json
{
  "schema_version": 1,
  "case_id": "00151e6a...",
  "task_type": "T2_response",
  "generated_at": "2026-08-20T10:00:00Z",
  "config_snapshot": {
    "noise_rows": 60, "episodes": 2,
    "prompt_versions": {"plan": "v1", "judge": "v1"},
    "model": "<生成模型名>"
  },
  "attempts": [
    {"attempt": 1, "rows_requested": 60, "rows_passed": 58,
     "gates": {"rule_rejected": 2, "judge_rejected": 3, "solvable": "valid"},
     "failure_reason": null}
  ],
  "final_status": "noisy",
  "rows": [
    {"csv_row": 57, "group_id": "<uuid>", "layer": "A", "episode_id": null,
     "category": "检验", "feature_name": "白细胞计数", "value": "5.2",
     "event_date": "2023-07-02", "judge": "pass"}
  ]
}
```

`final_status` ∈ `{"noisy", "degraded_clean"}`。
降级任务同样写 manifest（`rows: []`），保证目录内 manifest 恒存在、可批量统计。

## 7. 配置（`NoiseConfig`，单套全局参数）

```python
NoiseConfig(
    noise_rows=60,        # Layer A 行数
    episodes=2,           # 急性病程线条数
    retry_reduced=(30, 1),# 重试阶梯减量参数
    max_attempts=3,
    judge_batch_size=10,
    # 白名单/黑名单/日期规则等数据均在 catalog.py，不在此重复
)
```

- 不依赖 LLM API 种子；可复现性靠 manifest 的参数快照（模型名 + 提示词版本 + 参数），
  做到"参数级可追溯"，不承诺字节级复现
- 以后调整难度 = 改 `noise_rows` / `episodes` 重跑

## 8. 测试策略

1. **单元测试**（无 LLM）
   - catalog：红线清单完整性（肿瘤标志物/抗肿瘤药/禁用类别）
   - safety：日期窗口、关键证据日回避、schema 合法性、否认模式扫描、字面泄漏
   - materialize：17 字段齐全、group_id 唯一、subject 惯例采样
   - manifest：schema 往返、降级路径
   - 重试阶梯：mock 三道闸门，验证减量/降级/放行分支
2. **集成测试**（单任务 + stub client）
   - 对一个真实 v2 任务目录跑 `run_injection`：噪声行全部过闸门 1；
     manifest.rows 与 CSV 实际行一致；noisy CSV 行数 = 原行数 + 通过行数
3. **端到端试点**（真实 LLM，5~10 个任务）
   - 人工 review 噪声行真实感（像不像真实住院病历的杂音）
   - 用现有 Agent 工具层加载 noisy CSV：渲染、日期过滤、截断行为正常
   - Agent 在 2~3 个 noisy 任务上仍能得出 GT（定性确认难度上升但未破坏可解性）

## 9. 验收标准

- [ ] `pipeline/noise_injection/` 9 文件落地，catalog 声明表可独立 review
- [ ] v2 流水线插入 `inject_noise` 节点后，新生成任务自动带噪且 manifest 恒存在
- [ ] `scripts/apply_noise.py` 可 dry-run / resume / 断点续跑，存量任务产出 `tasks/oncology-v2-noisy/`
- [ ] 三道闸门全部生效；降级任务进 review_queue 且目录内为干净版
- [ ] 试点任务人工 review 通过：无 B 类矛盾、无肿瘤相关干扰、时间位置合理
- [ ] 单测 + 集成测试全部通过

## 10. 决策记录（brainstorming 留档）

| 决策 | 结论 |
|---|---|
| 噪声目标 | 检索/筛选难度（A 类：事实无关但真实），禁止矛盾/误导（B 类） |
| 噪声来源 | LLM 合成的常规/普通疾病记录；不用跨病例真实行 |
| 类别 | Layer A：评估/检验/用药/病程；Layer B：急性病程线；其余整类禁用 |
| 普通疾病用药 | 支持药 + 感冒/低热等急性用药（用户提出，纳入） |
| 共病线 | 本版本不做，架构留扩展位 |
| 数量 | ~60 行 + 2 条叙事线，单套全局参数，难度后续靠改参数 |
| 验证 | 三道闸门全上，每任务兜底（生成成本 +50% 可接受） |
| 存量任务 | 平行目录 `tasks/oncology-v2-noisy/`，原版不动 |
| 接入 | 流水线节点 + 独立脚本，两个入口共用一个核心包 |
| 指令 | 不提示存在噪声 |
| Seed | 不依赖 API 种子，manifest 记录参数快照 |
