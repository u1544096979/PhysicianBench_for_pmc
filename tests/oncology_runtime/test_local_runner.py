import logging
import csv
from pathlib import Path

import pytest

from data.oncology_complete_trajectory.index.build_index import REQUIRED_COLUMNS


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


def _write_case(root: Path, value: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    row = {column: "" for column in REQUIRED_COLUMNS}
    row.update(
        case_id="case-1",
        encnt_no="1",
        group_id="g1",
        subject="患者",
        feature_name="诊断名称",
        value=value,
        event_date="2026-01-01",
        category="诊断",
    )
    with (root / "case-1.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerow(row)


def test_cleaned_root_hides_raw_case_with_same_id(tmp_path):
    from agent.tool_registry import ToolRegistry, register_all_tools
    from scripts.run_task import resolve_cleaned_data_root

    _write_case(tmp_path / "raw" / "csv", "raw diagnosis")
    _write_case(tmp_path / "cleaned", "cleaned diagnosis")

    registry = ToolRegistry()
    register_all_tools(registry, data_root=resolve_cleaned_data_root(tmp_path))
    result = registry.dispatch("csv_search_diagnosis_events", {"case_id": "case-1"})

    assert [event["value"] for event in result["events"]] == ["cleaned diagnosis"]


def test_cleaned_root_cannot_escape_dataset_boundary(tmp_path):
    from scripts.run_task import resolve_cleaned_data_root

    dataset_root = tmp_path / "dataset"
    outside_root = tmp_path / "outside"
    dataset_root.mkdir()
    outside_root.mkdir()
    (dataset_root / "cleaned").symlink_to(outside_root, target_is_directory=True)

    with pytest.raises(ValueError, match="outside oncology data root"):
        resolve_cleaned_data_root(dataset_root)


def test_run_agent_uses_agent_eval_environment_and_cleaned_root(monkeypatch, tmp_path):
    from agent import llm_client, mini_agent, tool_registry
    from scripts import run_task

    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "instruction.md").write_text("Inspect case-1", encoding="utf-8")
    cleaned_root = tmp_path / "data" / "cleaned"
    cleaned_root.mkdir(parents=True)
    captured = {}

    monkeypatch.setenv("AGENT_EVAL_MODEL", "agent-model")
    monkeypatch.setenv("AGENT_EVAL_API_KEY", "agent-secret")
    monkeypatch.setenv("AGENT_EVAL_BASE_URL", "https://agent.example/v1")
    monkeypatch.setattr(
        llm_client,
        "LLMClient",
        lambda **kwargs: captured.setdefault("client", kwargs) or object(),
    )
    monkeypatch.setattr(
        tool_registry,
        "register_all_tools",
        lambda registry, data_root: captured.setdefault("data_root", data_root),
    )

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["agent"] = kwargs

        def run(self, instruction):
            return "done"

    monkeypatch.setattr(mini_agent, "MiniAgent", FakeAgent)

    assert run_task.run_agent(
        task_dir,
        tmp_path / "job",
        model=None,
        max_steps=5,
        temperature=None,
        parallel_tool_calls=True,
        reasoning_effort=None,
        data_root=cleaned_root,
    )
    assert captured["client"] == {
        "model_id": "agent-model",
        "api_key": "agent-secret",
        "base_url": "https://agent.example/v1",
    }
    assert captured["data_root"] == cleaned_root


def test_local_main_never_invokes_subprocess_and_has_one_job_dir_option(
    monkeypatch, tmp_path
):
    from scripts import job_manager, run_task

    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "instruction.md").write_text("Inspect case-1", encoding="utf-8")
    data_root = tmp_path / "data"
    (data_root / "cleaned").mkdir(parents=True)

    monkeypatch.setattr(
        run_task.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("local CSV runner invoked a subprocess"),
    )
    monkeypatch.setattr(job_manager, "write_metadata", lambda *args, **kwargs: None)

    parser = run_task.build_parser()
    assert sum(action.dest == "job_dir" for action in parser._actions) == 1
    assert run_task.main(
        [
            str(task_dir),
            "--data-root",
            str(data_root),
            "--job-dir",
            str(tmp_path / "job"),
            "--skip-agent",
            "--skip-eval",
        ]
    ) == 0
