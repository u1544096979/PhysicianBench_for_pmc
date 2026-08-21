"""闸门3：可解性复验（LLM solve 干净可见事件 + 全部噪声行，再评估答案）."""
from __future__ import annotations

from pipeline.oncology_generation.prompts_v2 import (
    build_evaluate_prompt,
    build_solve_prompt,
)


def _render_noise_rows(rows: list[dict]) -> str:
    """噪声行按与真实可见事件一致的渲染格式拼接（[组ID8] 日期 类别 + 字段全文）."""
    from pipeline.oncology_generation.schemas import (
        build_event_groups,
        serialize_groups,
    )
    events = []
    for i, r in enumerate(rows):
        cf = r["csv_fields"]
        events.append({**cf, "_source_row": f"N{i}"})
    groups = build_event_groups(events)
    return serialize_groups(groups, full=True)


def check(context, rows, client, *, visible_text: str | None = None) -> tuple[bool, str]:
    """干净可见事件 + 全部噪声行交给 LLM 求解，再用标准答案评估。

    verdict == "valid" 通过；否则 (False, detail)。
    visible_text 缺省时回退 context._visible_text / case_facts_text()。
    """
    if visible_text is None:
        visible_text = getattr(context, "_visible_text", "") or context.case_facts_text()
    noise_text = _render_noise_rows(rows)
    visible_events = visible_text + "\n" + noise_text

    solve_msgs = build_solve_prompt(context.instruction, visible_events)
    sol = client.chat_json(solve_msgs, node="noise_solve")
    answer = sol.get("answer", "")
    reasoning = sol.get("reasoning_summary", "")

    eval_msgs = build_evaluate_prompt(context.ground_truth, answer, reasoning)
    ev = client.chat_json(eval_msgs, node="noise_evaluate")
    verdict = ev.get("verdict", "inconsistent")
    if verdict == "valid":
        return True, ""
    return False, f"solvable verdict={verdict}: {ev.get('explanation', '')}"
