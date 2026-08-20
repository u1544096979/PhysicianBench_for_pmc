"""v2 流水线各节点中文 prompt."""
from __future__ import annotations

from typing import Any

from .task_types import TASK_TYPES, format_task_type_catalog

# ---------------------------------------------------------------------------
# ① 标注 + 推荐
# ---------------------------------------------------------------------------

LABEL_PROMPT = """\
你是医学benchmark任务设计专家。我们在基于肿瘤患者就诊轨迹构建临床推理benchmark。

【任务类型目录】
{catalog}

【某个患者病例的全部事件组摘要】（格式：[组ID前8位] 日期 类别，下一行为该组内字段： 值）
{groups_summary}

请判断这个病例轨迹适合生成哪些类型的任务，并推荐最适合的一种。

判断要求：
- 适用 = 该类型的答案记录（分期编码/疗效结论/标志物结果/诊断结论）在轨迹中确实存在，且其之前有相关证据事件
- 不要前置排除：唯一性、对比充分性、结果完整性由后续专门节点验证，标注阶段只做存在性初筛
- 多个类型符合存在性标准时都列入 applicable_types；推荐证据链最完整的一个
- 只有当轨迹中确实不存在任何类型的答案记录时，applicable_types 才返回空数组，recommended_type 返回 "none"

只输出JSON对象：
{{
  "applicable_types": ["T1_staging", ...],
  "recommended_type": "T2_response",
  "reason": "选择理由（1-2句话）"
}}"""


# ---------------------------------------------------------------------------
# ② 任务生成
# ---------------------------------------------------------------------------

GENERATE_PROMPT = """\
你是医学benchmark任务设计专家。请为下面这个肿瘤病例轨迹生成一道"{type_label}"（{type_code}）题目。

【任务类型适用条件】
{applicability}

【instruction 模板】（可以适度润色措辞，但必须保留结构化字段要求和 output/diagnosis_report.md 路径）
{instruction_template}

【ground_truth 字段要求】
{answer_schema_hint}

【患者病例的全部事件组】（格式：[组ID前8位] 日期 类别 + 组内事件明细）
{groups_full}

请完成：
1. 从事件组中选择一个最适合作为答案(target)的事件组：它必须是"{type_label}"类任务答案的直接载体（如分期记录/疗效结论/标志物结果/诊断结论），且它之前的事件构成可推理的证据链
2. 在所选事件组内，精确标记哪些事件构成答案：把直接写出答案结论的事件行号列入 answer_event_rows（行号=事件明细前的 [数字]）。同组内的检查所见、测量值、方法描述等证据性事件【不列入】，做题者需要靠它们推理出答案
3. 截断点 = 所选事件组中最早事件日期（此日期及之后的数据对做题者不可见，但 answer_event_rows 标记的答案事件会被单独隐藏，截断点之前仅隐藏这些行）
4. 基于模板生成instruction（模板中的{{target_date}}用截断点日期替换）
5. 从答案事件中提取 ground_truth（用病历记录的客观事实，不要自行推断或补编）

注意：
- 若上一个版本未通过验证，会附上失败反馈，请针对性地换一个target事件组或修改instruction，不要原样重复
- instruction 中不得出现答案的具体值（不得泄漏标签）

只输出JSON对象：
{{
  "target_group_id": "完整组ID（从事件组列表原样复制）",
  "target_date": "YYYY-MM-DD",
  "answer_event_rows": [行号1, 行号2, ...],
  "instruction": "完整的instruction文本",
  "deliverable": "output/diagnosis_report.md",
  "ground_truth": {{ ... 按 ground_truth 字段要求 ... }},
  "rationale": "为什么选这个事件组作为答案（1-2句话）"
}}"""


# ---------------------------------------------------------------------------
# ③ 静态验证
# ---------------------------------------------------------------------------

VALIDATE_PROMPT = """\
你是医学benchmark质量审查员。请审查下面这道题目（由生成器产出）是否合格。

【题目 instruction】
{instruction}

【标准答案（ground_truth）】
{ground_truth}

【做题者可见的轨迹】（截断点 {target_date} 之前的事件组全文；题目答案事件组本身及其后事件已移除）
{visible_groups}

逐项审查：
1. 泄漏检查：instruction 或可见轨迹中是否直接包含答案的具体值，使做题者无需推理即可抄录答案？
   （注意：可见轨迹中存在"强指向性证据"是合理的，那正是推理的依据；只有当答案值本身原样出现时才算泄漏）
2. 可回答性：基于可见轨迹，一个肿瘤科医生是否能够通过临床推理得到 ground_truth？
3. 较唯一性：可见轨迹是否还支持另一个明显不同且同样合理的答案？（如截断前已存在另一处分期记录）

只输出JSON对象：
{{
  "leaked": false,
  "answerable": true,
  "unique": true,
  "issues": ["问题描述（若有）"],
  "severity": "fatal|major|minor"
}}
判定规则：leaked=true 时 severity 必须为 fatal；answerable=false 或 unique=false 时 severity 至少 major；三项全过 passed 才为 true（由调用方计算）。"""


# ---------------------------------------------------------------------------
# ④ 做题
# ---------------------------------------------------------------------------

SOLVE_PROMPT = """\
你是一名肿瘤科医生，正在完成一道临床推理题。

【题目】
{instruction}

【你可见的患者病例数据】（题目评估时点之前的事件记录）
{visible_events}

请像临床医生一样完成这道题：
1. 先梳理关键证据（简要）
2. 给出你的最终答案（与题目要求的结构化字段一一对应）

只输出JSON对象：
{{
  "answer": "最终答案的紧凑文本（如：原发=升结肠腺癌, T4aN2aM1, IV期）",
  "answer_fields": {{ 与题目结构化字段对应的键值对 }},
  "reasoning_summary": "推理过程摘要（3-5句话，说明用了哪些证据）",
  "confidence": "high|medium|low",
  "cited_groups": ["引用的关键事件组ID前8位"]
}}"""


# ---------------------------------------------------------------------------
# ⑤ 答案评估
# ---------------------------------------------------------------------------

EVALUATE_PROMPT = """\
你是医学benchmark裁判。请对比做题者的答案与标准答案，判定这道题是否有效。

【标准答案（ground_truth）】
{ground_truth}

【做题者答案】
{answer}

【做题者推理摘要】
{reasoning}

判定规则：
- "valid"：答案与标准答案一致（临床等价也算一致，如"IIIC1r"与"III期(FIGO IIIC1r)"），且有真实推理过程
- "inconsistent"：答案与标准答案不一致，且推理看起来合理——说明轨迹支持多个答案，题目不唯一
- "instant_answer"：答案正确但推理摘要为空/仅复述单条记录/没有对比综合多个证据的过程——疑似答案泄漏或题目退化为检索题
- "insufficient_evidence"：做题者明确表示证据不足无法作答——说明截断点前证据链断裂

只输出JSON对象：
{{
  "verdict": "valid|inconsistent|instant_answer|insufficient_evidence",
  "consistent": true,
  "has_reasoning": true,
  "explanation": "判定说明（1-2句话）"
}}"""


# ---------------------------------------------------------------------------
# ⑥ checkpoint 生成
# ---------------------------------------------------------------------------

CHECKPOINT_PROMPT = """\
你是医学benchmark设计师。请为下面这道题生成评测检查点（checkpoint）。

【题目 instruction】
{instruction}

【标准答案（ground_truth）】
{ground_truth}

【截断前可见轨迹的事件类别清单】（做题agent可查询的类别）
{available_categories}

【本题型checkpoint设计要求】
{checkpoints_hint}

checkpoint分四层，每条必须指定评测方式：
- data_retrieval（数据获取）：检查agent是否查询了关键类别。eval_method="category_query"，params: {{"category": "病理", "description": "查询病理事件"}}
- clinical_reasoning（临床推理）：检查推理中间步骤是否正确。eval_method="llm_judge"，params: {{"question": "是否正确识别原发肿瘤部位？", "expected": " ..."}}
- outcome_check（结果判定）：检查最终结构化字段。eval_method="field_match"，params: {{"field": "总分期", "expected": "从ground_truth提取的期望值"}}
- documentation（文档完整）：检查输出文档。eval_method="llm_judge"，params: {{"question": "输出是否包含全部要求的结构化字段？", "expected": "字段清单"}}

要求：
- 总数4-8条，四层各至少1条
- outcome_check 的 expected 值必须从 ground_truth 中原样提取，不得改写
- data_retrieval 的 category 必须从上面"可查询类别清单"中选择真实存在的类别

只输出JSON对象：
{{
  "checkpoints": [
    {{
      "checkpoint_id": "cp1_data_pathology",
      "layer": "data_retrieval",
      "description": "中文描述",
      "eval_method": "category_query",
      "params": {{}}
    }}
  ]
}}"""


# ---------------------------------------------------------------------------
# prompt 构造函数
# ---------------------------------------------------------------------------

def build_label_prompt(groups_summary: str) -> list[dict[str, str]]:
    return [
        {"role": "user", "content": LABEL_PROMPT.format(
            catalog=format_task_type_catalog(),
            groups_summary=groups_summary,
        )},
    ]


def build_generate_prompt(
    task_type: str,
    groups_full: str,
    feedback_history: list[str] | None = None,
) -> list[dict[str, str]]:
    t = TASK_TYPES[task_type]
    extra = ""
    if feedback_history:
        bullets = "\n".join(f"- {fb}" for fb in feedback_history[-3:])
        extra = f"\n【上一版本的失败反馈（务必针对性修正）】\n{bullets}\n"
    # instruction_template 内部含 {target_date} 等留给LLM填的占位符，
    # 需转义大括号避免 str.format 解析
    escaped_template = t.instruction_template.replace("{", "{{").replace("}", "}}")
    content = GENERATE_PROMPT.format(
        type_label=t.label,
        type_code=t.code,
        applicability=t.applicability,
        instruction_template=escaped_template,
        answer_schema_hint=t.answer_schema_hint,
        groups_full=groups_full,
    ) + extra
    return [{"role": "user", "content": content}]


def build_validate_prompt(
    instruction: str,
    ground_truth: dict[str, Any],
    target_date: str,
    visible_groups: str,
) -> list[dict[str, str]]:
    return [
        {"role": "user", "content": VALIDATE_PROMPT.format(
            instruction=instruction,
            ground_truth=_json(ground_truth),
            target_date=target_date,
            visible_groups=visible_groups,
        )},
    ]


def build_solve_prompt(instruction: str, visible_events: str) -> list[dict[str, str]]:
    return [
        {"role": "user", "content": SOLVE_PROMPT.format(
            instruction=instruction,
            visible_events=visible_events,
        )},
    ]


def build_evaluate_prompt(
    ground_truth: dict[str, Any],
    answer: str,
    reasoning: str,
) -> list[dict[str, str]]:
    return [
        {"role": "user", "content": EVALUATE_PROMPT.format(
            ground_truth=_json(ground_truth),
            answer=answer,
            reasoning=reasoning,
        )},
    ]


def build_checkpoint_prompt(
    instruction: str,
    ground_truth: dict[str, Any],
    available_categories: list[str],
    task_type: str,
) -> list[dict[str, str]]:
    t = TASK_TYPES[task_type]
    return [
        {"role": "user", "content": CHECKPOINT_PROMPT.format(
            instruction=instruction,
            ground_truth=_json(ground_truth),
            available_categories="、".join(available_categories),
            checkpoints_hint=t.checkpoints_hint,
        )},
    ]


def _json(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, indent=None)
