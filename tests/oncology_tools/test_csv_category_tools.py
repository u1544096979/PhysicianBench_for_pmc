from pathlib import Path

from agent.tool_registry import ToolRegistry, register_all_tools
from tools.csv_category_tools import CATEGORY_TOOL_SPECS, build_category_schemas


def test_registry_exposes_14_category_tools_plus_file(tmp_path: Path):
    registry = ToolRegistry()
    register_all_tools(registry, tmp_path)
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
