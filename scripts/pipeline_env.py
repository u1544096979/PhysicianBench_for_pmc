"""Stage-specific model environment configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelEnv:
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


def load_model_env(prefix: str) -> ModelEnv:
    """Load model settings from ``<PREFIX>_*`` environment variables."""
    normalized_prefix = prefix.strip().upper().rstrip("_")
    if not normalized_prefix:
        raise ValueError("prefix must be non-empty")

    env_prefix = normalized_prefix + "_"
    values = {
        key[len(env_prefix):]: value
        for key, value in os.environ.items()
        if key.startswith(env_prefix) and value
    }
    model = values.pop("MODEL", None)
    api_key = values.pop("API_KEY", None)
    base_url = values.pop("BASE_URL", None)
    if bool(api_key) != bool(base_url):
        raise ValueError(
            f"{normalized_prefix}_API_KEY and {normalized_prefix}_BASE_URL "
            "must be configured together"
        )
    return ModelEnv(model=model, api_key=api_key, base_url=base_url, extra=values)
