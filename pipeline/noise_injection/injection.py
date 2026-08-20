"""噪声注入编排：planner → materialize → 闸门1(规则安全) → 闸门2(逐行裁判,
被拒行重生成一次再判) → 闸门3(可解性复验)；重试阶梯 §4.2 与降级路径."""
from __future__ import annotations
import time
from dataclasses import dataclass, field

from . import catalog, materialize as M
from .plan import NoisePlanner
from .judge import NoiseJudge
from .safety import run_safety_gate
from . import solvable as S
from .manifest import build_manifest


@dataclass
class InjectionResult:
    final_status: str               # noisy | degraded_clean
    rows: list[dict]                # passed noise rows（17 字段，无元字段）
    manifest: dict
    attempts: list[dict] = field(default_factory=list)
    review_queue_entries: list[dict] = field(default_factory=list)
    degrade_reason: str | None = None


def _model_name(client) -> str:
    return getattr(getattr(client, "_client", None), "model", "") or getattr(client, "model", "unknown")


def planner_version() -> str:
    from . import prompts as NP
    return NP.PROMPT_VERSIONS["plan"]


def judge_version() -> str:
    from . import prompts as NP
    return NP.PROMPT_VERSIONS["judge"]


def _manifest_rows(rows: list[dict]) -> list[dict]:
    """从通过闸门的物化行顶层元字段生成 manifest rows（非 csv_fields）."""
    return [{"group_id": r["group_id"], "layer": r.get("layer", "A"),
             "episode_id": r.get("episode_id"),
             "category": r["category"], "feature_name": r["feature_name"],
             "value": r["value"], "event_date": r["event_date"], "judge": "pass"}
            for r in rows]


def run_injection(context, config, client, *, visible_text=None,
                  full_attempts=None) -> InjectionResult:
    planner = NoisePlanner(client)
    judge = NoiseJudge(client)
    # 重试阶梯 §4.2：首档满量，后续档减量；full_attempts 截断（调试用）
    ladder = [(config.noise_rows, config.episodes)] + [config.retry_reduced] * (config.max_attempts - 1)
    if full_attempts is not None:
        ladder = ladder[:full_attempts]
    attempts: list[dict] = []
    degrade_reason = None

    for idx, (n_rows, n_ep) in enumerate(ladder, start=1):
        try:
            plan = planner.plan(context, noise_rows=n_rows, episodes=n_ep)
            mat_rows = M.materialize(context, plan)
            g1_passed, g1_rej = run_safety_gate(context, mat_rows)
            # 闸门2：逐行裁判；被拒行重生成一次再判，仍拒则丢弃
            judged, g2_rej = judge.judge(context, g1_passed,
                                         batch_size=config.judge_batch_size)
            if g2_rej:
                regen_plan = planner.plan(context, noise_rows=len(g2_rej), episodes=0)
                regenerated = M.materialize(context, regen_plan)
                for rr in regenerated:
                    rr["judge_status"] = "pending"
                rp, rj = judge.judge(context, regenerated,
                                     batch_size=config.judge_batch_size)
                judged = judged + rp
                g2_rej = g2_rej + rj
            # 闸门3：可解性（visible_text 由调用方传入真实可见事件文本）
            ok, detail = S.check(context, judged, client, visible_text=visible_text)
            attempts.append({
                "attempt": idx, "rows_requested": n_rows + n_ep,
                "rows_passed": len(judged),
                "gates": {"rule_rejected": len(g1_rej), "judge_rejected": len(g2_rej),
                          "solvable": "valid" if ok else ("failed:" + detail)},
                "failure_reason": None if ok else detail,
            })
            if ok:
                return _build_result(context, config, client, judged, attempts, "noisy")
            degrade_reason = detail
        except Exception as exc:  # noqa: BLE001 - 单档异常不中断，走后续重试档/降级
            attempts.append({"attempt": idx, "rows_requested": n_rows + n_ep,
                             "rows_passed": 0, "gates": {},
                             "failure_reason": f"exception: {exc}"})
            degrade_reason = str(exc)

    return _build_result(context, config, client, [], attempts, "degraded_clean",
                         degrade_reason=degrade_reason)


def _build_result(context, config, client, judged, attempts, final_status,
                  degrade_reason=None) -> InjectionResult:
    """judged=通过闸门的完整行（含 layer/episode_id 元字段）；内部 csv_row 化 + manifest rows."""
    final_rows = [M.csv_row(r) for r in judged]
    manifest = build_manifest(
        case_id=context.case_id, task_type=context.task_type,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        config_snapshot={
            "noise_rows": config.noise_rows, "episodes": config.episodes,
            "prompt_versions": {"plan": planner_version(), "judge": judge_version()},
            "model": _model_name(client),
        },
        attempts=attempts, final_status=final_status, rows=_manifest_rows(judged),
        degrade_reason=degrade_reason,
    )
    entries = []
    if final_status == "degraded_clean":
        entries.append({
            "case_id": context.case_id, "reason_class": "noise_gate_failed",
            "detail": degrade_reason or "noise gates all failed",
            "attempts": attempts,
        })
    return InjectionResult(final_status=final_status, rows=final_rows, manifest=manifest,
                           attempts=attempts, review_queue_entries=entries,
                           degrade_reason=degrade_reason)
