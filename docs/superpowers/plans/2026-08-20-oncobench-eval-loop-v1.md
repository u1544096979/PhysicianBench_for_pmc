# Implementation Plan: OncoBench 评测闭环 v1

- **Spec**: `docs/superpowers/specs/2026-08-20-oncobench-eval-loop-v1.md`（Approved）
- **日期**: 2026-08-20
- **分支**: `feat/eval-loop`（从 `feat/task-generation-v2` 切出）
- **原则**: 工具层新写（旧csv_category_tools归档不删）；MiniAgent小改；执行器全新

---

## Task 1: OncologyTools 工具层（17工具）

**新增**: `tools/oncology_tools.py`

1. `CATEGORY_TOOL_MAP`: 14个类别→工具函数一一对齐（诊断/病理/影像/用药/检验/病史/查体/手术/病程/入院/出院/会诊/评估/不良反应）
2. 每工具签名统一: `(start_date: str | None, end_date: str | None) -> str`；case_id由环境注入不暴露给模型
3. `query_keyword(keyword)`: value/extra_value/feature_name子串匹配（casefold）
4. `query_date_range(start_date, end_date)`: 跨全类别
5. `write_file(path, content)`: 限`output/`前缀，路径逃逸防护
6. 返回格式：每行`[行号] 日期 [类别] 字段名: 值 (extra; 方法:x; 单位:y)`——与任务生成侧full_text同构，模型熟悉
7. 50行截断 + "结果过多，建议用start_date/end_date缩小范围"提示
8. 空结果返回："该类别在指定范围内无记录"（不返回裸空串）

**修改**: `tools/csv_event_store.py` —— query()过滤简化：删除subject/feature_name/group_id三道滤网及对应参数；日期参数改`start_date/end_date`（ISO，含端点）；保留行号注入与排序

**测试**: `tests/test_oncology_tools.py`
- 14类别工具：正常查/日期过滤/空结果提示
- keyword：大小写不敏感/跨字段命中/中文
- date_range：端点包含
- write_file：正常写入/路径逃逸拒绝
- 50行截断提示
- store过滤简化后：仅category+日期生效

## Task 2: MiniAgent 考生化改造

**修改**: `agent/mini_agent.py` + `agent/prompts.py` + `llm/client.py`

1. `llm/client.py`: 加`AGENT_LLM_BASE_URL/API_KEY/MODEL/MAX_TOKENS`环境变量组；`get_agent_client()`工厂（未配置时回退GEN_LLM_*，再回退报错）
2. `agent/prompts.py`: 新`ONCOLOGY_SYSTEM_PROMPT`——角色（肿瘤科医生）、14类数据导航清单、17工具使用规范、日期ISO格式要求、"信息在截断时点之前"提醒、write_file报告结构要求
3. `agent/mini_agent.py`: 工具注册表指向OncologyTools；LLM调用走agent client；工具调用few-shot示例注入
4. 旧FHIR prompt保留在文件里注释标记deprecated（不删，git有历史）

**测试**: `tests/test_agent_setup.py`
- agent client环境变量优先级（AGENT_>GEN_>报错）
- 工具注册表17个齐全
- system prompt含14类导航

## Task 3: Checkpoint 执行器

**新增**: `evaluation/checkpoint_executor.py`

1. `execute_checkpoints(task_dir, trajectory, agent_report) -> Scorecard`
2. 分派逻辑按layer：
   - `data_retrieval`（代码）: checkpoint.params.target含工具名/类别 → 比对trajectory工具调用记录（命中=pass）
   - `outcome_check`（代码）: 从agent_report抽结构化字段（按instruction要求的"- 字段: 值"格式解析）→ 与ground_truth对应字段比对；同义词表（ALK抑制剂≈阿来替尼≈Alectinib；CR/PR/SD/PD中英文）+大小写不敏感
   - `clinical_reasoning`/`documentation`（LLM）: 裁判prompt携带checkpoint描述+ground_truth+报告原文（全量），要求输出`{"verdict":"pass/fail","comment":"引用报告原句的评语"}`；裁判走GEN client
3. Scorecard落盘 `evaluation/results/<task_id>/<run_ts>/scorecard.json`
4. LLM裁判调用失败：该cp标记`verdict:"error"`不中断整体

**测试**: `tests/test_checkpoint_executor.py`
- data_retrieval命中/未命中
- outcome_check同义词/字段缺失
- LLM层mock返回pass/fail/error三分支
- scorecard JSON schema校验

## Task 4: 运行CLI + 闭环集成

**新增**: `scripts/run_oncology_task.py`

```
python -m scripts.run_oncology_task --task-dir tasks/oncology-v2/<id> [--max-turns 30]
流程: 载入任务包 → 构造OncologyTools(清洗CSV) → MiniAgent解题(记录trajectory)
     → 读output/diagnosis_report.md → execute_checkpoints → 落盘scorecard+trajectory
```

**集成测试**: `tests/test_eval_loop_integration.py`（fake LLM全链路）
- 工具调用→报告→判分→scorecard全流程
- 泄漏题00813296跑通不崩溃（结果标记known-leak）

## Task 5: 真实跑2道题验收

1. `.env`确认AGENT_LLM_*配置（首跑=qwen3.8同GEN）
2. 跑00151e6a（验收题）→ 检查scorecard：期望6cp大部分pass（考生是qwen3.8自己出的题，应当能做对）
3. 跑00813296（泄漏题参考）→ 预期高分（答案可见），验证"泄漏题得高分"这个反向信号——将来可以用"接近满分"当泄漏筛查启发式
4. 人工读两份trajectory+scorecard，确认判分评语合理（A4）
5. 全测试套件绿 → commit → 汇报

## 执行顺序

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 5（严格串行，每步测试绿再下一步）
```

## 明确不做

- pass@k多次采样
- 多模型实验矩阵
- Docker
- 旧15工具的行为兼容（归档即可，测试重写）
