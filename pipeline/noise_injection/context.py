from __future__ import annotations
import csv
from dataclasses import dataclass, field
from collections import OrderedDict, defaultdict

from . import catalog


@dataclass(frozen=True)
class CaseContext:
    case_id: str
    task_type: str
    target_date: str
    first_event_date: str
    instruction: str
    ground_truth: dict
    key_evidence_dates: tuple[str, ...] = field(default_factory=tuple)
    denial_terms: tuple[str, ...] = field(default_factory=tuple)
    convention_by_category: dict = field(default_factory=dict)
    matrix_rows: tuple[dict, ...] = field(default_factory=tuple)  # raw event dicts
    encnt_no: str = ""

    def case_facts_text(self) -> str:
        """注入给 LLM 的病例事实摘要（避免矛盾噪声，不泄露标准答案值）."""
        return ("病例ID=%s；评估时点（截断日）=%s；首个事件日期=%s"
                % (self.case_id, self.target_date, self.first_event_date))

    def visible_noise_abs_dates(self) -> list[str]:
        return sorted(set(str(r.get("event_date", "")) for r in self.matrix_rows if r.get("event_date")))


def _first_event(rows) -> str:
    dates = [str(r.get("event_date", "")).strip() for r in rows if r.get("event_date")]
    return min(dates) if dates else ""


def _extract_denials(rows) -> list[str]:
    """从 病史/诊断 行提取 '否认 X（史）' 的 X，支持 '否认 A、B（史）' 枚举形式."""
    import re
    terms: list[str] = []
    for r in rows:
        cat = r.get("category", "")
        if cat not in ("病史", "诊断"):
            continue
        text = " ".join(filter(None, [str(r.get(k, "")) for k in
                                      ("feature_name", "value", "extra_value", "actual_value")]))
        for m in re.finditer(r"否认\s*([^，。；\s]{1,40})", text):
            for part in re.split(r"[、，,]", m.group(1)):
                t = part.strip().rstrip("史").strip()
                if t and t not in terms and len(t) <= 8:
                    terms.append(t)
    return terms


def _convention_for(rows, category: str) -> dict:
    """从该病例同类别既有行采样惯例值；缺失回退 catalog 默认."""
    conv: dict = {}
    base = dict(catalog.DEFAULT_CONVENTIONS[category])
    keys = ("subject", "method", "source", "_record_source", "pipeline_version", "feature_type")
    for room, ok in [("评估", ("评估",)), ("检验", ("检验",)), ("用药", ("用药",)), ("病程", ("病程",))]:
        if room != category:
            continue
        cnt: dict[str, dict[str, int]] = {k: defaultdict(int) for k in keys}
        for r in rows:
            if r.get("category", "") != ok[0]:
                continue
            for k in keys:
                v = str(r.get(k, "") or "")
                if v:
                    cnt[k][v] += 1
        for k in keys:
            if cnt[k]:
                conv[k] = max(cnt[k], key=cnt[k].get)
    for k in keys:
        conv[k] = conv.get(k) or base[k]
    return conv


def _is_marker_bearing(r) -> bool:
    """任一内容字段（feature_name/value/extra_value/actual_value）含肿瘤标志物
    （大小写不敏感子串，不限类别）即视为标志物行."""
    for k in ("feature_name", "value", "extra_value", "actual_value"):
        v = str(r.get(k, "") or "")
        if any(m.casefold() in v.casefold() for m in catalog.TUMOR_MARKERS):
            return True
    return False


def _key_evidence_dates(rows, target_group_id: str, target_date: str) -> list[str]:
    """关键证据日 = 目标组日期 + 可见集合中任一内容字段含肿瘤标志物的行日期 + 影像组日期."""
    dates: list[str] = []
    target_date_seen = False
    for r in rows:
        gid = r.get("group_id", "")
        cat = r.get("category", "")
        if gid == target_group_id:
            if r.get("event_date"):
                dates.append(str(r.get("event_date")))
            target_date_seen = True
            continue  # 只取其日期
        if target_date_seen:
            continue  # 目标组之后不可见
        d = str(r.get("event_date", "") or "")
        if not d:
            continue
        if cat == "影像" or _is_marker_bearing(r):
            dates.append(d)
    # 规范化为该组 event_date 去重（同一组可能多行同日期）
    return list(OrderedDict.fromkeys(d for d in dates if d))


def build_context(*, case_id, events, task_type, target_group_id, target_date,
                  instruction, ground_truth, answer_event_rows=None) -> CaseContext:
    rows = list(events)
    ctx = CaseContext(
        case_id=case_id,
        task_type=task_type,
        target_date=target_date,
        first_event_date=_first_event(rows),
        instruction=instruction,
        ground_truth=ground_truth,
        key_evidence_dates=tuple(_key_evidence_dates(rows, target_group_id, target_date)),
        denial_terms=tuple(_extract_denials(rows)),
        convention_by_category={c: _convention_for(rows, c) for c in catalog.ALLOWED_CATEGORIES},
        matrix_rows=tuple(rows),
    )
    object.__setattr__(ctx, "encnt_no", _first_encnt(rows))
    return ctx


def _first_encnt(rows) -> str:
    for r in rows:
        v = str(r.get("encnt_no", "") or "")
        if v:
            return v
    return ""


def case_from_csv(case_id: str, csv_path, *, task_type, target_group_id, target_date,
                  instruction, ground_truth, answer_event_rows=None) -> CaseContext:
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        events = [r for r in reader if any((v or "").strip() for v in r.values())]
    return build_context(
        case_id=case_id, events=events, task_type=task_type,
        target_group_id=target_group_id, target_date=target_date,
        instruction=instruction, ground_truth=ground_truth,
        answer_event_rows=answer_event_rows,
    )
