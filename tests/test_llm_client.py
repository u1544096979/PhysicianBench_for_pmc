"""agent.llm_client.LLMClient 后端自动探测与显式覆盖测试."""
import logging


def test_llm_client_keeps_backend_auto_detection_when_no_override(monkeypatch):
    from agent import llm_client

    captured = {}
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://fallback.example/v1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm_client.openai, "OpenAI", lambda **kwargs: captured.update(kwargs) or object())

    llm_client.LLMClient(model_id="fallback-model")

    assert captured == {
        "api_key": "fallback-secret",
        "base_url": "https://fallback.example/v1",
    }


def test_llm_client_accepts_independent_explicit_overrides_without_logging_secrets(
    monkeypatch, caplog
):
    from agent import llm_client

    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://fallback.example/v1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm_client.openai, "OpenAI", lambda **kwargs: calls.append(kwargs) or object())

    with caplog.at_level(logging.INFO):
        llm_client.LLMClient(model_id="key-only", api_key="key-only-secret")
        llm_client.LLMClient(model_id="url-only", base_url="https://url-only.example/v1")

    assert calls == [
        {"api_key": "key-only-secret", "base_url": "https://fallback.example/v1"},
        {"api_key": "fallback-secret", "base_url": "https://url-only.example/v1"},
    ]
    assert "key-only-secret" not in caplog.text
