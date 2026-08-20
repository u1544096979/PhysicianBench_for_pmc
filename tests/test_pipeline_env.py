"""scripts.pipeline_env 阶段环境变量（GENERATION_* / AGENT_EVAL_*）解析测试."""


def test_model_envs_are_independent_and_capture_extra_values(monkeypatch):
    from scripts.pipeline_env import load_model_env

    monkeypatch.setenv("GENERATION_MODEL", "generation-model")
    monkeypatch.setenv("GENERATION_API_KEY", "generation-secret")
    monkeypatch.setenv("GENERATION_BASE_URL", "https://generation.example/v1")
    monkeypatch.setenv("GENERATION_TIMEOUT", "45")
    monkeypatch.setenv("AGENT_EVAL_MODEL", "agent-model")
    monkeypatch.setenv("AGENT_EVAL_API_KEY", "agent-secret")
    monkeypatch.setenv("AGENT_EVAL_BASE_URL", "https://agent.example/v1")
    monkeypatch.setenv("AGENT_EVAL_REASONING_EFFORT", "high")

    generation = load_model_env("GENERATION")
    agent_eval = load_model_env("AGENT_EVAL")

    assert generation.model == "generation-model"
    assert generation.api_key == "generation-secret"
    assert generation.base_url == "https://generation.example/v1"
    assert generation.extra == {"TIMEOUT": "45"}
    assert agent_eval.model == "agent-model"
    assert agent_eval.api_key == "agent-secret"
    assert agent_eval.base_url == "https://agent.example/v1"
    assert agent_eval.extra == {"REASONING_EFFORT": "high"}


def test_model_env_is_empty_when_stage_variables_are_unset(monkeypatch):
    from scripts.pipeline_env import ModelEnv, load_model_env

    for key in list(__import__("os").environ):
        if key.startswith("GENERATION_"):
            monkeypatch.delenv(key, raising=False)

    assert load_model_env("GENERATION") == ModelEnv()
