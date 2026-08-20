"""Checkpoint 执行器：四层判分（spec §6）.

- data_retrieval: 代码判分——查 call_log 中类别工具是否被调用（params含target关键词）
- outcome_check: 代码判分——报告字段抽取 + GT字段同义词匹配
- clinical_reasoning / documentation: LLM裁判（必须引用报告原文）
- LLM失败不中断：verdict=error，整体继续
"""
from __future__ import annotations

import json
import re
from typing import Any

from llm.client import LLMClient

# ------------------------------------------------------------------
# 工具调用记录分析（data_retrieval）
# ------------------------------------------------------------------

CATEGORY_TOOLS = {
    "query_diagnosis", "query_pathology", "query_imaging", "query_medication",
    "query_lab", "query_history", "query_physical_exam", "query_surgery",
    "query_course", "query_admission", "query_discharge", "query_consultation",
    "query_assessment", "query_adverse_event",
}


def eval_data_retrieval(cp: dict[str, Any], call_log: list[dict]) -> dict[str, Any]:
    """target: 期望被查询的类别关键词（如 "影像"）或工具名（如 query_imaging）。"""
    params = cp.get("params", {})
    target = str(params.get("category") or params.get("target") or cp.get("target") or "")
    if not target:
        return {"verdict": "error", "judge": "code", "comment": "checkpoint缺target参数"}

    tgt = target.lower()
    for call in call_log:
        tool = call.get("tool", "")
        if tgt == tool.lower():
            return {"verdict": "pass", "judge": "code", "comment": f"调用了 {tool}"}
        if tool in CATEGORY_TOOLS:
            from tools.oncology_tools import TOOL_CATEGORY_MAP
            cat = TOOL_CATEGORY_MAP.get(tool, "")
            if cat and (tgt in cat.lower() or tgt in tool.lower()):
                return {"verdict": "pass", "judge": "code", "comment": f"调用了 {tool}（类别: {cat}）"}
        if tool == "query_keyword" and tgt in json.dumps(call.get("args", {}), ensure_ascii=False).lower():
            return {"verdict": "pass", "judge": "code", "comment": f"query_keyword 检索了 '{target}'"}
    return {"verdict": "fail", "judge": "code", "comment": f"未检索与 '{target}' 相关的记录"}


# ------------------------------------------------------------------
# 报告字段抽取与匹配（outcome_check）
# ------------------------------------------------------------------

SYNONYMS: dict[str, list[str]] = {
    "pr": ["pr", "部分缓解", "partial response"],
    "cr": ["cr", "完全缓解", "complete response"],
    "sd": ["sd", "疾病稳定", "稳定", "stable disease"],
    "pd": ["pd", "疾病进展", "进展", "progressive disease"],
    "alk抑制剂": ["alk抑制剂", "alk抑制剂靶向", "阿来替尼", "alectinib", "克唑替尼", "塞瑞替尼", "lorlatinib", "布格替尼", "恩沙替尼"],
    "alk抑制剂靶向治疗": ["alk抑制剂", "alk抑制剂靶向", "阿来替尼", "alectinib"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s)).lower()


def _value_hits(expected: str, report: str) -> bool:
    e = _norm(expected)
    r = _norm(report)
    if not e:
        return False
    if e in r:
        return True
    for syn in SYNONYMS.get(e, []):
        if _norm(syn) in r:
            return True
    return False


def _extract_field(report: str, field_label: str) -> str | None:
    for line in report.splitlines():
        m = re.match(rf"[-\s*]*{re.escape(field_label)}\s*[:：]\s*(.+)", line.strip())
        if m and m.group(1).strip() and not m.group(1).strip().startswith("["):
            return m.group(1).strip()
    return None


def eval_outcome_check(cp: dict[str, Any], report: str, ground_truth: dict[str, Any]) -> dict[str, Any]:
    params = cp.get("params", {}) or {}
    gt_field = str(params.get("gt_field") or params.get("field") or "")
    field_label = str(params.get("report_label") or gt_field or "")
    if not gt_field:
        return {"verdict": "error", "judge": "code", "comment": "checkpoint缺gt_field参数"}

    expected = params.get("expected")
    if expected is None:
        expected = ground_truth.get(gt_field)
    if expected is None:
        return {"verdict": "error", "judge": "code", "comment": f"GT无字段 {gt_field}"}

    extracted = _extract_field(report, field_label) if field_label else None
    scope = extracted if extracted else report
    if _value_hits(expected, scope) or (extracted and _value_hits(expected, extracted)):
        comment = f"字段{gt_field}匹配期望值" + (f"（抽取自报告行: {extracted[:40]}）" if extracted else "（全文匹配）")
        return {"verdict": "pass", "judge": "code", "comment": comment}
    return {
        "verdict": "fail", "judge": "code",
        "comment": f"字段{gt_field}期望[{expected}]未匹配（报告{'行: '+extracted[:40] if extracted else '全文未含'}）",
    }


# ------------------------------------------------------------------
# LLM 裁判
# ------------------------------------------------------------------

JUDGE_PROMPT = """\
你是医学benchmark裁判。评估考生报告是否达成检查点要求。

【检查点】{check_desc}
{extra_rule}

【考生报告】
{report}

只输出JSON：
{{"verdict": "pass|fail", "comment": "评语必须引用报告原文片段作为依据"}}"""


def eval_llm_judge(cp: dict[str, Any], report: str, client: LLMClient) -> dict[str, Any]:
    layer = cp.get("layer", "")
    desc = cp.get("description", cp.get("check", ""))
    extra = ""
    if layer == "clinical_reasoning":
        extra = "重点评估：推理链是否使用了病例证据、逻辑是否成立、结论是否由证据支撑。"
    elif layer == "documentation":
        extra = "重点评估：题目要求的结构化字段是否齐全、格式是否规范。"
    prompt = [{"role": "user", "content": JUDGE_PROMPT.format(
        check_desc=desc, extra_rule=extra, report=report[:6000],
    )}]
    try:
        resp = client.chat_json(prompt, node="judge", soft_retry=1)
        verdict = str(resp.get("verdict", "fail")).lower()
        verdict = verdict if verdict in ("pass", "fail") else "fail"
        comment = str(resp.get("comment", ""))[:500]
        return {"verdict": verdict, "judge": "llm", "comment": comment}
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "error", "judge": "llm", "comment": f"judge调用失败: {exc}"[:300]}


# ------------------------------------------------------------------
# 主入口
# ------------------------------------------------------------------

def execute_checkpoints(
    checkpoints: list[dict[str, Any]],
    *,
    report_text: str,
    ground_truth: dict[str, Any],
    call_log: list[dict],
    judge_client: LLMClient | None = None,
) -> dict[str, Any]:
    results = []
    n_pass = n_fail = n_err = 0
    for cp in checkpoints:
        layer = cp.get("layer", "")
        if layer == "data_retrieval":
            r = eval_data_retrieval(cp, call_log)
        elif layer == "outcome_check":
            r = eval_outcome_check(cp, report_text, ground_truth)
        elif layer in ("clinical_reasoning", "documentation"):
            if judge_client is None:
                r = {"verdict": "error", "judge": "llm", "comment": "未配置裁判LLM"}
            else:
                r = eval_llm_judge(cp, report_text, judge_client)
        else:
            r = {"verdict": "error", "judge": "none", "comment": f"未知layer: {layer}"}
        verdict = r["verdict"]
        if verdict == "pass":
            n_pass += 1
        elif verdict == "fail":
            n_fail += 1
        else:
            n_err += 1
        results.append({
            "checkpoint_id": cp.get("checkpoint_id") or cp.get("id") or "?",
            "layer": layer,
            "description": cp.get("description", cp.get("check", "")),
            **r,
        })
    return {
        "total": len(results),
        "pass": n_pass,
        "fail": n_fail,
        "error": n_err,
        "score": round(n_pass / len(results), 3) if results else 0.0,
        "results": results,
    }
