from __future__ import annotations
from . import prompts as NP


class NoisePlanner:
    def __init__(self, client, prompt_version: str | None = None):
        self.client = client
        self.prompt_version = prompt_version or NP.PROMPT_VERSIONS["plan"]

    def plan(self, context, *, noise_rows: int, episodes: int) -> dict:
        resp = self.client.chat_json(
            NP.build_plan_prompt(context, noise_rows=noise_rows, episodes=episodes),
            node="noise_plan",
        )
        # 防御性规范化
        if not isinstance(resp, dict):
            raise ValueError("plan LLM 未返回对象")
        resp.setdefault("layer_a", [])
        resp.setdefault("episodes", [])
        return resp
