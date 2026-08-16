from pathlib import Path

import pytest

from agent.tool_registry import ToolRegistry, register_all_tools
from tools.csv_category_tools import CATEGORY_TOOL_SPECS, build_category_schemas


def test_registry_exposes_14_category_tools_plus_file(tmp_path: Path):
    registry = ToolRegistry()
    register_all_tools(registry, tmp_path, workspace_root=tmp_path / "workspace")
    assert len(CATEGORY_TOOL_SPECS) == 14
    assert len(registry.tool_names) == 15
    assert "write_file" in registry.tool_names
    assert set(registry.tool_names) == {spec[1] for spec in CATEGORY_TOOL_SPECS} | {"write_file"}


def test_category_schemas_require_case_and_describe_event_shape():
    schemas = build_category_schemas()
    assert len(schemas) == 14
    for schema in schemas:
        assert "CSV" in schema["description"]
        assert "subject-feature-value" in schema["description"]
        assert schema["parameters"]["required"] == ["case_id"]
        assert set(schema["parameters"]["properties"]) == {"case_id", "subject", "feature_name", "event_date", "group_id", "limit"}


def test_write_file_is_restricted_to_workspace(tmp_path: Path):
    workspace = tmp_path / "job" / "workspace"
    registry = ToolRegistry()
    register_all_tools(registry, tmp_path / "cleaned", workspace_root=workspace)

    output = workspace / "output" / "answer.md"
    result = registry.dispatch(
        "write_file",
        {"file_path": str(output), "content": "diagnosis"},
    )

    assert result["status"] == "ok"
    assert output.read_text(encoding="utf-8") == "diagnosis"


@pytest.mark.parametrize("relative_target", ["raw/case.csv", "task/ground_truth.json", "logs/agent.txt"])
def test_write_file_rejects_paths_outside_workspace(tmp_path: Path, relative_target: str):
    workspace = tmp_path / "job" / "workspace"
    registry = ToolRegistry()
    register_all_tools(registry, tmp_path / "cleaned", workspace_root=workspace)
    target = tmp_path / relative_target

    result = registry.dispatch(
        "write_file",
        {"file_path": str(target), "content": "overwrite"},
    )

    assert "error" in result
    assert not target.exists()


def test_write_file_rejects_relative_and_symlink_escape(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    registry = ToolRegistry()
    register_all_tools(registry, tmp_path / "cleaned", workspace_root=workspace)

    relative = registry.dispatch("write_file", {"file_path": "output.md", "content": "x"})
    escaped = registry.dispatch(
        "write_file",
        {"file_path": str(workspace / "escape" / "answer.md"), "content": "x"},
    )

    assert "error" in relative
    assert "error" in escaped
    assert not (outside / "answer.md").exists()
