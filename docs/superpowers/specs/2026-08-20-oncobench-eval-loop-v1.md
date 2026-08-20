# Spec: OncoBench 评测闭环 v1（17工具 + MiniAgent 考生 + Checkpoint 执行器）

- **日期**: 2026-08-20
- **状态**: Approved（2026-08-20 用户批准）
- **分支**: `feat/task-generation-v2`（继续用）或新开 `feat/eval-loop`
- **上游依赖**: 任务生成流水线v2（已完成，产出 `tasks/oncology-v2/` 任务包）
- **范围**: 工具层改造 + 考生agent对接 + 判分执行器 + 2道题闭环验收

---

## 1. 背景与动机

任务生成流水线v2已能产出干净任务包（instruction + ground_truth + checkpoints + cleaned_trajectory）。但目前：

1. 工具层是魔改遗留版：15个工具带subject/feature_name/group_id过滤参数——这些字段跨case波动大、group_id将弃用，不能当查询锚点
2. MiniAgent的LLM后端写死，无法更换被测模型
3. checkpoints.json是声明式数据，没有执行器——评分点还是纸面设计

本spec打通"考生读题→调工具查截断轨迹→写报告→四层checkpoint判分→得分卡"完整闭环。**这是benchmark存在的意义**：任务包只有能被真实agent作答并自动评分，才成为benchmark。

## 2. 目标

### 必须达成

- G1: 17个新工具实现并注册进MiniAgent（14类别查询一一对齐 + keyword + date_range + write_file）
- G2: CsvEventStore过滤简化：只留category+日期两道滤网，拆掉subject/feature_name/group_id
- G3: MiniAgent的LLM后端可配置（`AGENT_LLM_*`环境变量组，与出题侧`GEN_LLM_*`分离），system prompt重写（去FHIR表述、14类导航、工具使用规范）
- G4: Checkpoint执行器：按layer分派——data_retrieval/outcome_check代码判分，clinical_reasoning/documentation由LLM裁判（qwen3.8）判分
- G5: 2道已验证任务包（00151e6a、00813296中的干净者）× MiniAgent跑通，每题产出：trajectory日志 + 得分卡（cp逐项pass/fail + LLM裁判评语）

### 不做（Non-Goals）

- 不做写入类工具（医嘱/处方/转诊）——T1-T4只写报告
- 不做多模型对比实验（接口留好，实验是论文阶段的事）
- 不做Docker沙箱（用户明确：暂不搭）
- 不做pass@k多次采样（先单次跑通）
- 不改任务生成流水线（已定稿，case 4行标错类问题明确不修）

## 3. 决策记录（brainstorming已确认）

| # | 决策 | 来源 |
|---|---|---|
| E1 | 工具过滤只用category+日期，subject/feature_name/group_id不入参不匹配 | 用户：字段波动大/group_id弃用 |
| E2 | 一工具一category，14类全覆盖，不合并映射 | 用户：68不映射两个 |
| E3 | 评估/不良反应类照常出工具——截断已删答案行，查到的是历史评估（合法线索），工具不做二次防御 | 用户拍板 |
| E4 | 类别导航写进system prompt（14类清单+各自工具名），不出独立导航工具 | 用户：导航退化成提示词 |
| E5 | query_feature（按字段名查）砍掉——feature_name跨case不统一，查不出东西 | 用户 |
| E6 | 被测模型=MiniAgent+可配置LLM后端，先qwen3.8自测（自评偏置已知，写进局限） | Q2/Q3讨论 |
| E7 | 判分LLM=qwen3.8（三角色同模型，pilot可接受） | Q3确认 |
| E8 | 日期参数=start_date/end_date双参数ISO格式，废弃"2021-08..2021-11"字符串范围 | 我提议，随spec确认 |
| E9 | 返回行带源行号（判分时可定位考生引用的证据行） | Q3解释后默认采纳 |
| E10 | 不搭Docker，本地进程跑 | 用户 |

## 4. 工具层规范

### 4.1 工具清单（17个）

**14个类别查询工具**（结构完全一致，仅category不同）：

| 工具名 | category |
|---|---|
| query_diagnosis | 诊断 |
| query_pathology | 病理 |
| query_imaging | 影像 |
| query_medication | 用药 |
| query_lab | 检验 |
| query_history | 病史 |
| query_physical_exam | 查体 |
| query_surgery | 手术 |
| query_course | 病程 |
| query_admission | 入院 |
| query_discharge | 出院 |
| query_consultation | 会诊 |
| query_assessment | 评估 |
| query_adverse_event | 不良反应 |

统一签名：

```python
def query_xxx(start_date: str | None = None, end_date: str | None = None) -> list[EventRow]
```

- case_id不入参——运行环境从任务目录注入（考生固定身份查自己的case）
- 日期可选，ISO "YYYY-MM-DD"，含当天；不传=该类别全时段
- **第15类"其他"（238条）无专属工具**，system prompt明示用query_keyword兜底

**3个通用工具：**

```python
def query_keyword(keyword: str) -> list[EventRow]
# 在全部类别的 value / extra_value / feature_name 三列做子串匹配
# 大小写不敏感；keyword为必填，空串返回友好错误

def query_date_range(start_date: str, end_date: str) -> list[EventRow]
# 跨全部14+1类的时间窗查询

def write_file(path: str, content: str) -> str
# 考生写报告；path固定校验 output/ 前缀（防路径逃逸，沿用现有实现）
```

### 4.2 EventRow返回格式

每行返回9字段+行号（与数据表字段集一致）：

```json
{"row": 48, "event_date": "2021-10-28", "category": "影像",
 "subject": "", "feature_name": "影像所见", "value": "双肺弥漫性病灶较前退缩",
 "actual_value": "", "extra_value": "", "unit": "", "method": "CT"}
```

### 4.3 返回上限与排序

- 排序：event_date升序，同日期按源行号
- 上限：单次返回50行；超出时返回前50+提示"结果共N条，已截断，请用日期参数缩小范围"

### 4.4 CsvEventStore简化

- `EventQuery`字段删到：`category: str | None`、`start_date`、`end_date`（keyword查询独立方法`search_keyword`新增）
- 删除`_date_matches`的"YYYY-MM..YYYY-MM"范围串支持，改双参数比较
- 旧15工具文件`csv_category_tools.py`废弃归档（git留痕）

## 5. 考生侧（MiniAgent）规范

### 5.1 LLM后端可配置

`.env`新增（与GEN_LLM分离）：

```
AGENT_LLM_BASE_URL=...
AGENT_LLM_API_KEY=...
AGENT_LLM_MODEL=...          # 默认回落GEN_LLM_MODEL（qwen3.8）
AGENT_LLM_MAX_TOKENS=8192
```

client实现复用`llm/client.py`的LLMClient类，参数化实例化（不加新依赖）。

### 5.2 System Prompt重写（中文）

结构（大致400-600字）：

```
你是一名肿瘤科医生，正在完成一份临床评估任务。
你可以通过病例查询工具访问患者的就诊数据。

【数据导航】本病例数据共15类：诊断/病理/影像/用药/检验/病史/查体/手术/
病程/入院/出院/会诊/评估/不良反应（各有一一对应的query_工具），
另有"其他"类可用 query_keyword 全文检索。

【任务】（注入instruction.md内容）

【工具使用规范】
- 先查询证据再下结论；引用证据时注明日期
- 单次查询结果可能截断，可用日期参数缩小范围
- 最终答案写入 output/diagnosis_report.md（write_file）
```

### 5.3 运行入口

新CLI：`python -m scripts.run_oncology_task --task <task_dir> [--model xxx]`

- 加载任务包（instruction + cleaned_trajectory.csv）
- 构造该case专属的EventStore（数据根=任务包内cleaned CSV）
- 启动MiniAgent循环（沿用现有ReAct实现：步数上限/重复检测/trajectory日志）
- 结束后调用判分，产出报告

## 6. 判分执行器规范

### 6.1 Checkpoint分派逻辑

读取`checkpoints.json`，按layer分派：

| layer | 判分方式 | 实现 |
|---|---|---|
| data_retrieval | 代码 | 解析trajectory日志的工具调用序列。checkpoint.params携带期望（如`{"category":"影像"}`）→ 检查调用序列中存在匹配调用。兼容params缺失时降级为LLM裁判 |
| outcome_check | 代码 | 解析考生write_file的报告内容，正则/字段抽取期望值（如response="PR"）→ 与ground_truth精确匹配（大小写不敏感；支持中英文同义词表，如PR=部分缓解=Partial Response） |
| clinical_reasoning | LLM裁判 | prompt含：instruction + 考生报告 + checkpoint.description + ground_truth相关字段 → 输出pass/fail/评语 |
| documentation | LLM裁判 | prompt含：考生报告 + instruction要求的结构化字段清单 → 检查字段齐全性 + 内容具体性 |

### 6.2 LLM裁判prompt要点

- 输出JSON：`{"checkpoint_id": "...", "verdict": "pass/fail", "comment": "一句话理由"}`
- 裁判温度0（若端点支持）；qwen3.8需带enable_thinking=False（复用client）
- clinical_reasoning裁判必须引用考生报告原文片段作为评语依据

### 6.3 得分卡输出

`tasks/oncology-v2/<task_id>/runs/<timestamp>/scorecard.json`：

```json
{"task_id": "...", "model": "qwen3.8", "finished_at": "...",
 "total_checkpoints": 6, "passed": 5,
 "details": [
   {"cp": "cp1", "layer": "data_retrieval", "verdict": "pass", "judge": "code", "comment": "调用了query_imaging"},
   {"cp": "cp3", "layer": "clinical_reasoning", "verdict": "fail", "judge": "llm", "comment": "未对比基线尺寸，直接给结论"}
 ],
 "report_excerpt": "疗效结论：PR ...(前200字)"}
```

同目录落`trajectory.json`（MiniAgent既有日志格式）。

## 7. 验收标准

| # | 标准 |
|---|---|
| A1 | 17工具全部实现+注册；单测覆盖（正常查询/日期过滤/截断提示/keyword大小写/空结果友好提示/路径逃逸防护） |
| A2 | MiniAgent换后端不改代码：改.env的AGENT_LLM_MODEL即生效（验证方式：mock两个模型名跑通同一任务） |
| A3 | 2道任务包（00151e6a确认干净；00813296带已知泄漏、结果标注"泄漏题参考跑"）各跑1次，无崩溃，产出trajectory+scorecard |
| A4 | scorecard格式符合6.3；code判分层不调LLM；llm判分层评语非空且引用报告原文 |
| A5 | 全部新旧单测绿（旧csv工具测试随归档删除/重写） |

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| qwen3.8做考生可能工具调用格式错误率高 | system prompt给工具调用few-shot示例；MiniAgent已有重试/纠错逻辑沿用 |
| 50行截断导致考生漏看关键证据 | 截断提示明确引导缩日期；评测维度本身包含"信息检索效率"（data_retrieval层天然测这个） |
| 裁判与考生同模型自评偏置 | 已知局限（E6/E7），得分卡标注model=judge model；论文阶段分离 |
| 00151e6a题的GT含"ALK抑制剂"字段，考生表述可能为"阿来替尼"等别名 | outcome_check匹配用同义词表；LLM裁判兜底判断语义等价 |

## 9. 后续迭代（不在本期）

- pass@k多次采样与pass^k
- 多模型对比实验矩阵
- review_queue人工审核界面
- 生成-评测联动（评测失败率回流任务质量分析）
