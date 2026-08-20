"""单任务 / 批量生成入口使用 GENERATION_* 环境变量测试."""

import pytest


def test_single_generation_entry_uses_generation_environment(monkeypatch, tmp_path):
    from scripts import generate_oncology_task

    captured = {}
    monkeypatch.setenv("GENERATION_MODEL", "generation-model")
    monkeypatch.setenv("GENERATION_API_KEY", "generation-secret")
    monkeypatch.setenv("GENERATION_BASE_URL", "https://generation.example/v1")
    monkeypatch.setattr(
        generate_oncology_task,
        "LLMClient",
        lambda **kwargs: captured.update(kwargs) or object(),
    )
    monkeypatch.setattr(
        generate_oncology_task,
        "run_generation",
        lambda *args, **kwargs: {"validation_errors": ["stop after client creation"]},
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "generate_oncology_task.py",
            "case-1",
            "--data-root",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit, match="generation rejected"):
        generate_oncology_task.main()

    assert captured == {
        "model_id": "generation-model",
        "api_key": "generation-secret",
        "base_url": "https://generation.example/v1",
    }


def test_batch_generation_entry_uses_generation_environment(monkeypatch, tmp_path):
    from scripts import generate_all_oncology_tasks

    captured = {}
    monkeypatch.setenv("GENERATION_MODEL", "batch-generation-model")
    monkeypatch.setenv("GENERATION_API_KEY", "batch-generation-secret")
    monkeypatch.setenv("GENERATION_BASE_URL", "https://batch-generation.example/v1")
    monkeypatch.setattr(
        generate_all_oncology_tasks,
        "LLMClient",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    generate_all_oncology_tasks.generate_all_cases(tmp_path, tmp_path / "tasks", case_ids=[])

    assert captured == {
        "model_id": "batch-generation-model",
        "api_key": "batch-generation-secret",
        "base_url": "https://batch-generation.example/v1",
    }
