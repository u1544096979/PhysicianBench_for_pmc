from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class NoiseConfig:
    noise_rows: int = 60          # Layer A 行数
    episodes: int = 2             # Layer B 急性病程线条数
    retry_reduced: tuple[int, int] = (30, 1)  # 重试阶梯减量 (noise_rows, episodes)
    max_attempts: int = 3
    judge_batch_size: int = 10
