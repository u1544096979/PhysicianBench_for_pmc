from __future__ import annotations
import re

from . import catalog
from .context import CaseContext


def row_text(row: dict) -> str:
    cf = row["csv_fields"]
    return " ".join(str(cf.get(k, "") or "") for k in
                    ("feature_name", "value", "actual_value", "extra_value", "unit", "method"))


def _denial_trigger(text: str, denial_terms) -> str | None:
    for t in denial_terms:
        if t and str(t).strip() and (t in text or t.replace("史", "") in text):
            return t
    return None


def check_row(ctx: CaseContext, row: dict) -> tuple[bool, str | None]:
    cf = row["csv_fields"]
    cat = cf["category"]
    date = cf.get("event_date", "") or ""
    # 1) 类别白名单
    if cat not in catalog.ALLOWED_CATEGORIES:
        return False, f"禁用类别:{cat}"
    # 2) 日期窗口 [first, target_date)
    if not (ctx.first_event_date <= date < ctx.target_date):
        return False, f"日期出窗:{date}"
    # 3) 关键证据日回避（保守：所有噪声行均避开）
    if date in ctx.key_evidence_dates:
        return False, f"关键证据日:{date}"
    # 4) 类别内禁用术语
    text = row_text(row)
    for term in catalog.FORBIDDEN_TERMS_BY_CATEGORY.get(cat, ()):
        if term and term in text:
            return False, f"禁用术语[{cat}]:{term}"
    # 5) 全局肿瘤标志物/抗肿瘤药/禁用类别术语
    hits = catalog.scan_forbidden(text)
    if hits:
        return False, "扫描命中:" + ";".join(hits)
    # 6) 否认模式扫描
    trig = _denial_trigger(text, ctx.denial_terms)
    if trig:
        return False, f"否认冲突:{trig}"
    # 7) feature_type 合法 / 数值行 unit+value 可解析
    ft = cf.get("feature_type", "")
    if ft not in catalog.FEATURE_TYPES:
        return False, f"非法feature_type:{ft}"
    if ft == "数值型":
        if not cf.get("unit"):
            return False, "数值行缺unit"
        try:
            float(str(cf.get("value", "")).replace("×", "e").replace("^", "").strip())
        except ValueError:
            return False, f"数值不可解析:{cf.get('value')}"
    return True, None


def _literal_leak(ctx: CaseContext, rows) -> str | None:
    """GT 值字面泄漏：去空白后子串匹配；len<3 的 GT 值不做字面检查."""
    gt_values = [str(v).strip() for v in ctx.ground_truth.values()
                 if isinstance(v, (str, int, float)) and len(str(v).strip()) >= 3]
    if not gt_values:
        return None
    for r in rows:
        t = re.sub(r"\s+", "", row_text(r))
        for v in gt_values:
            v_norm = re.sub(r"\s+", "", v)
            if v_norm and v_norm in t:
                return f"GT值 '{v}' 出现在噪声行"
    return None


def run_safety_gate(ctx: CaseContext, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """闸门1（零 LLM）：逐行规则检查 + GT 值字面泄漏检查."""
    passed: list[dict] = []
    rejections: list[dict] = []
    for i, r in enumerate(rows):
        ok, reason = check_row(ctx, r)
        if not ok:
            rejections.append({"index": i, "reason": reason, "row": r.get("csv_fields", {})})
            continue
        passed.append(r)
    leak = _literal_leak(ctx, passed)
    if leak:
        # 泄漏 → 清空（重建依赖重试阶梯）
        return [], rejections + [{"index": "leak", "reason": leak, "row": {}}]
    return passed, rejections
