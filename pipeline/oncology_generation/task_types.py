"""T1-T4 任务类型配置（中文，直接供 prompt 拼接）."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskTypeDef:
    code: str
    label: str
    applicability: str
    instruction_template: str
    answer_schema_hint: str
    checkpoints_hint: str


TASK_TYPES: dict[str, TaskTypeDef] = {
    "T1_staging": TaskTypeDef(
        code="T1_staging",
        label="分期判定",
        applicability=(
            "轨迹中存在明确记录肿瘤分期的诊断或病理事件组（如 临床分期/病理分期/TNM/FIGO/AJCC 编码），"
            "且该事件组之前有可支撑分期判定的证据（病理报告、影像检查、体格检查等）。"
            "若截断前已存在另一条分期记录导致答案不唯一，则不适合。"
        ),
        instruction_template=(
            "你是一名肿瘤科医生。\n"
            "当前评估时点：{target_date}。\n"
            "你只能通过病例查询工具访问该时点之前已经发生的病例数据。\n\n"
            "任务：根据该患者的病理检查和影像学结果，判定肿瘤的分期。\n\n"
            "请基于查询到的证据完成判断，并将最终结果保存为 output/diagnosis_report.md。\n"
            "文件必须包含以下结构化字段：\n"
            "- 原发肿瘤部位：[填写]\n"
            "- T分期：[填写]\n"
            "- N分期：[填写]\n"
            "- M分期：[填写]\n"
            "- 分期系统：[TNM/FIGO/AJCC等]\n"
            "- 总分期：[填写]\n"
            "- 判定依据：[列出关键证据]"
        ),
        answer_schema_hint=(
            'ground_truth 必须包含: staging_system(分期系统), overall_stage(总分期), '
            'T/N/M(如可得), primary_site(原发部位)'
        ),
        checkpoints_hint=(
            "data_retrieval 层至少包含：查询病理类事件、查询影像类事件；"
            "outcome_check 层至少包含：总分期正确；"
            "clinical_reasoning 层至少包含：正确识别原发肿瘤部位。"
        ),
    ),
    "T2_response": TaskTypeDef(
        code="T2_response",
        label="疗效评估",
        applicability=(
            "轨迹中存在明确记录疗效结论的评估事件组（如 CR/PR/SD/PD、完全缓解/部分缓解/稳定/进展），"
            "且该事件组之前有至少两次可对比的疗效证据（影像评估、肿瘤标志物、体格检查等）。"
            "若疗效结论缺乏前后对比依据，则不适合。"
        ),
        instruction_template=(
            "你是一名肿瘤科医生。\n"
            "当前评估时点：{target_date}。\n"
            "你只能通过病例查询工具访问该时点之前已经发生的病例数据。\n\n"
            "任务：根据该患者治疗过程中的疗效相关检查结果，按照RECIST 1.1标准评估当前疗效。\n\n"
            "请基于查询到的证据完成判断，并将最终结果保存为 output/diagnosis_report.md。\n"
            "文件必须包含以下结构化字段：\n"
            "- 评估时点前主要治疗：[填写]\n"
            "- 可评估病灶情况：[描述]\n"
            "- 疗效结论：[CR/PR/SD/PD]\n"
            "- 判定依据：[列出关键证据]"
        ),
        answer_schema_hint=(
            'ground_truth 必须包含: response(疗效结论 CR/PR/SD/PD), prior_treatment(评估前治疗), '
            'evidence_summary(依据摘要)'
        ),
        checkpoints_hint=(
            "data_retrieval 层至少包含：查询基线与随访疗效证据（影像/标志物）；"
            "outcome_check 层至少包含：疗效结论正确；"
            "clinical_reasoning 层至少包含：识别了可评估病灶或对比依据。"
        ),
    ),
    "T3_biomarker": TaskTypeDef(
        code="T3_biomarker",
        label="分子标志物解读",
        applicability=(
            "轨迹中存在明确记录分子标志物状态的病理/检验事件组（如 HER2/ER/PR/KRAS/EGFR/MSI/MMR/PD-L1 "
            "等检测及结果），且该事件组之前有病理诊断等背景证据。"
            "若仅有检测项目名而无明确结果记录，则不适合。"
        ),
        instruction_template=(
            "你是一名分子病理科医生。\n"
            "当前评估时点：{target_date}。\n"
            "你只能通过病例查询工具访问该时点之前已经发生的病例数据。\n\n"
            "任务：根据该患者的病理检查和分子检测结果，解读关键分子标志物的状态及其临床意义。\n\n"
            "请基于查询到的证据完成判断，并将最终结果保存为 output/diagnosis_report.md。\n"
            "文件必须包含以下结构化字段：\n"
            "- 标志物名称：[填写]\n"
            "- 检测结果：[填写]\n"
            "- 检测方法：[填写]\n"
            "- 临床意义：[填写]\n"
            "- 判定依据：[列出关键证据]"
        ),
        answer_schema_hint=(
            'ground_truth 必须包含: biomarker(标志物名称), status(检测结果), '
            'method(检测方法), clinical_significance(临床意义)'
        ),
        checkpoints_hint=(
            "data_retrieval 层至少包含：查询病理/免疫组化/基因检测事件；"
            "outcome_check 层至少包含：标志物状态正确；"
            "clinical_reasoning 层至少包含：临床意义解读正确。"
        ),
    ),
    "T4_diagnosis": TaskTypeDef(
        code="T4_diagnosis",
        label="诊断推理",
        applicability=(
            "轨迹中存在首次明确恶性肿瘤诊断的诊断事件组，且该事件组之前有完整的证据链"
            "（病史、影像、病理、检验等至少两类）。"
            "若诊断之前证据过于稀薄（只有病史或只有检验），则不适合。"
        ),
        instruction_template=(
            "你是一名肿瘤科医生。\n"
            "当前评估时点：{target_date}。\n"
            "你只能通过病例查询工具访问该时点之前已经发生的病例数据。\n\n"
            "任务：根据该患者的病史、检查和病理结果，推断原发肿瘤诊断及转移情况。\n\n"
            "请基于查询到的证据完成判断，并将最终结果保存为 output/diagnosis_report.md。\n"
            "文件必须包含以下结构化字段：\n"
            "- 原发肿瘤：[填写]\n"
            "- 组织学类型：[填写]\n"
            "- 转移情况：[填写]\n"
            "- 判定依据：[列出关键证据]"
        ),
        answer_schema_hint=(
            'ground_truth 必须包含: primary_tumor(原发肿瘤), histology(组织学类型), '
            'metastasis(转移情况)'
        ),
        checkpoints_hint=(
            "data_retrieval 层至少包含：查询影像与病理事件；"
            "outcome_check 层至少包含：原发肿瘤正确；"
            "clinical_reasoning 层至少包含：转移情况推断合理。"
        ),
    ),
}


def format_task_type_catalog() -> str:
    """①标注节点用的类型目录文本."""
    lines = []
    for t in TASK_TYPES.values():
        lines.append(f"### {t.code} {t.label}\n适用条件：{t.applicability}")
    return "\n\n".join(lines)
