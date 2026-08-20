from __future__ import annotations
from .catalog import ALLOWED_CATEGORIES

PROMPT_VERSIONS = {"plan": "v1", "judge": "v1"}

PLAN_PROMPT = """\
你是医学数据合成专家。要为一份肿瘤住院病历补充大量"事实无关但真实"的常规医疗记录（噪声），以加大信息检索难度，但绝不引入与答案矛盾或指向肿瘤相关的干扰。噪声必须"事实无关"，不是"与答案矛盾"。

【病例上下文】
- case_id: {case_id}
- 任务类型: {task_type}
- 评估时点（截断日）: {target_date}
- 病例首个事件日期: {first_event_date}
- 关键证据日期（噪声叙事线必须避开）: {key_dates}
- 该患者既往史否认项（噪声不得含）: {denial_terms}

【硬性红线】
1. 只允许类别: {categories}。严禁出现 影像/病理/手术/入院/出院/诊断/病史/其他/会诊 类别。
2. 严禁肿瘤标志物（CEA/AFP/CA125/CA19-9/PSA/NSE/LDH等）、抗肿瘤药物（化疗/靶向/免疫治疗/内分泌治疗）。
3. 严禁疗效/分期信号：疗效评估、治疗反应、随访结果、分期、TNM、ECOG、PFS/OS、周期数。
4. 所有事件日期 ∈ [{first_event_date}, {target_date})，严格早于评估时点。
5. Layer A 评分/检验数值须正常或轻度异常；用药只用支持治疗药（护胃/抗凝/维生素/补液/缓泻）。
6. 时间规则：生命体征按日分布；检验成簇（入院、治疗中期、评估前一周各一簇）；急性病程线 2~4 天自包含、置于时间窗中段、避开关键证据日期。

【输出要求】只输出一个 JSON 对象：
{{
  "layer_a": [
    {{"category": "评估|检验|用药|病程", "feature_name": "...", "value": "...",
      "unit": "..." , "event_date": "YYYY-MM-DD", "note": "一句说明，不入CSV"}}
  ],
  "episodes": [
    {{"episode_id": "ep1", "title": "轻微低热小病程",
      "days": [
        {{"category": "病程", "feature_name": "病程", "value": "今日患者体温38.2°C，伴畏寒、纳差", "date_abs": "YYYY-MM-DD"}},
        {{"category": "评估", "feature_name": "体温", "value": "38.2", "unit": "℃", "date_abs": "YYYY-MM-DD"}},
        {{"category": "用药", "feature_name": "药品名称", "value": "对乙酰氨基酚", "unit": "0.5g 口服", "date_abs": "YYYY-MM-DD"}},
        {{"category": "病程", "feature_name": "病程", "value": "体温恢复正常，食欲改善", "date_abs": "YYYY-MM-DD"}}
      ]}}
  ]
}}
Layer A 共 {noise_rows} 行；episodes 共 {episodes} 条，每条内日期链自洽且逐日+1~2天，全部 date_abs 落在时间窗内、避开关键证据日期。"""

JUDGE_PROMPT = """\
你是医学噪声裁判。下面这条添加进肿瘤病历的噪声记录，需与【标准答案】及【病例事实】核对。判据：
- related_to_answer=true：该行包含与最终答案同源的信息（会直接提示答案，或属于答案推理所必需的证据类型）。
- contradicts=true：该行与标准答案或病例既定事实相矛盾、会误导推理。

【标准答案】
{ground_truth}

【病例事实】
{case_facts}

【待审单行（JSON）】
{row_json}

只输出 JSON：{{"row_id": {row_id}, "related_to_answer": false, "contradicts": false, "reason": "简短理由"}}"""


def build_plan_prompt(context, *, noise_rows, episodes) -> list[dict]:
    from .config import NoiseConfig  # ensure config importable
    content = PLAN_PROMPT.format(
        case_id=context.case_id, task_type=context.task_type,
        target_date=context.target_date, first_event_date=context.first_event_date,
        key_dates="、".join(context.key_evidence_dates) or "无",
        denial_terms="、".join(context.denial_terms) or "无",
        categories="、".join(ALLOWED_CATEGORIES),
        noise_rows=noise_rows, episodes=episodes,
    )
    return [{"role": "user", "content": content}]


def build_judge_prompt(context, row, row_id=None) -> list[dict]:
    import json
    payload = row.get("csv_fields", row) if isinstance(row, dict) else row
    content = JUDGE_PROMPT.format(
        ground_truth=json.dumps(context.ground_truth, ensure_ascii=False),
        case_facts=context.case_facts_text(),
        row_json=json.dumps(payload, ensure_ascii=False),
        row_id=row_id,
    )
    return [{"role": "user", "content": content}]
