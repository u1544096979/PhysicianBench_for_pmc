from __future__ import annotations
from . import prompts as NP


class NoiseJudge:
    """闸门2：LLM 逐行裁判。拒绝 related_to_answer 或 contradicts 为真的噪声行."""

    def __init__(self, client, prompt_version: str | None = None,
                 batch_size: int | None = None):
        self.client = client
        self.prompt_version = prompt_version or NP.PROMPT_VERSIONS["judge"]
        # 可选构造期默认值；judge() 显式 batch_size 优先，缺省回退 10
        self.batch_size = batch_size

    def _judge_one(self, context, row) -> tuple[bool, str]:
        rid = row.get("group_id", "")[:8]
        resp = self.client.chat_json(
            NP.build_judge_prompt(context, row, rid), node="noise_judge",
        )
        related = bool(resp.get("related_to_answer", False))
        contra = bool(resp.get("contradicts", False))
        reason = str(resp.get("reason", ""))
        if related or contra:
            return False, reason or ("related" if related else "contradicts")
        return True, reason

    def judge(self, context, rows, batch_size: int | None = None):
        bs = batch_size or self.batch_size or 10
        passed: list[dict] = []
        rejections: list[dict] = []
        total = len(rows)
        for start in range(0, total, bs):
            batch = rows[start:start + bs]
            for i, r in enumerate(batch):
                ok, reason = self._judge_one(context, r)
                if not ok:
                    rejections.append({"index": start + i, "reason": reason,
                                       "row": r.get("csv_fields", {})})
                else:
                    r["judge_status"] = "pass"
                    passed.append(r)
        return passed, rejections
