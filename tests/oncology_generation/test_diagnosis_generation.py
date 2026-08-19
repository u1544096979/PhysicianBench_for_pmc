import csv
from pathlib import Path

import pytest

from pipeline.oncology_generation.graph import build_generation_graph
from pipeline.oncology_generation.nodes import parse_model_json, select_target_group
from pipeline.oncology_generation.schemas import EventGroup
from tools.csv_event_types import EVENT_COLUMNS


def _write_case(root: Path, target_value: str = "肺腺癌") -> None:
    source = root / "raw" / "csv" / "case-1.csv"
    source.parent.mkdir(parents=True)
    fields = [*EVENT_COLUMNS, "source_extra"]
    rows = [
        {"case_id": "case-1", "group_id": "g1", "event_date": "2024-01-01", "category": "病史", "feature_name": "症状", "value": "咳嗽"},
        {"case_id": "case-1", "group_id": "g2", "event_date": "2024-01-02", "category": "病理", "feature_name": "病理诊断", "value": target_value, "source_extra": "源文件扩展列"},
        {"case_id": "case-1", "group_id": "g3", "event_date": "2024-01-03", "category": "手术", "feature_name": "治疗", "value": "切除"},
    ]
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in fields} for row in rows])


class FakeClient:
    def chat(self, messages):
        prompt = messages[0]["content"]
        assert "不得泄漏目标组的 value" in prompt
        assert "必须使用中文" in prompt
        assert "target_group_id" in prompt
        return type("Response", (), {"content": '{"target_group_id":"g2","selection_rationale":"明确病理诊断","role":"肿瘤科医生","instruction":"请判断诊断并说明依据。","deliverable":"诊断意见"}'})()


class JsonClient:
    def __init__(self, content):
        self.content = content

    def chat(self, messages):
        return type("Response", (), {"content": self.content})()


class CaseInsensitiveLeakClient:
    def chat(self, messages):
        return type("Response", (), {"content": '{"target_group_id":"g2","selection_rationale":"明确病理诊断","role":"oncologist","instruction":"The likely stage is iiia.","deliverable":"诊断意见"}'})()


@pytest.mark.parametrize("content", ["[]", "null", '"text"'])
def test_parse_model_json_rejects_non_object_top_level(content):
    with pytest.raises(ValueError, match="object"):
        parse_model_json(JsonClient(content), "prompt")


def test_parse_model_json_extracts_fenced_object():
    result = parse_model_json(JsonClient('```json\n{"target_group_id": "g2"}\n```'), "prompt")

    assert result == {"target_group_id": "g2"}


def test_select_target_group_rejects_incomplete_model_result():
    class IncompleteClient:
        def chat(self, messages):
            return type("Response", (), {"content": '{"target_group_id":"g2","role":"oncologist","instruction":"请判断。","deliverable":"诊断意见"}'})()

    events = [{"_source_row": "2", "group_id": "g2", "category": "病理", "feature_name": "病理诊断", "value": "肺腺癌"}]
    state = {"raw_events": events, "event_groups": [EventGroup("g2", "2024-01-01", 2, "病理", events)]}

    with pytest.raises(ValueError, match="selection_rationale"):
        select_target_group(state, IncompleteClient())


def test_select_target_group_indexes_real_group_and_drafts_task():
    events = [{"_source_row": "2", "group_id": "g2", "category": "病理", "feature_name": "病理诊断", "value": "肺腺癌"}]
    state = {"raw_events": events, "event_groups": [EventGroup("g2", "2024-01-01", 2, "病理", events)]}
    result = select_target_group(state, FakeClient())
    assert result["target_group_id"] == "g2"
    assert result["target_events"] == events
    assert result["task_draft"]["instruction"] == "请判断诊断并说明依据。"


def test_graph_uses_fixed_diagnosis_generation_sequence(tmp_path):
    _write_case(tmp_path)
    state = build_generation_graph(tmp_path, FakeClient(), set()).invoke({"case_id": "case-1"})
    assert state["review_status"] == "approved"
    assert state["target_group_id"] == "g2"
    assert state["target_events"][0]["value"] == "肺腺癌"
    assert state["cleaned_path"] == tmp_path / "cleaned" / "case-1.csv"


def test_graph_rejects_case_insensitive_target_value_leak(tmp_path):
    _write_case(tmp_path, target_value="IIIA")
    final_cleaned = tmp_path / "cleaned" / "case-1.csv"
    final_cleaned.parent.mkdir()
    final_cleaned.write_text("existing cleaned data\n", encoding="utf-8")

    state = build_generation_graph(tmp_path, CaseInsensitiveLeakClient(), set()).invoke({"case_id": "case-1"})

    assert state["review_status"] == "needs_revision"
    assert any("instruction" in error and "value" in error for error in state["validation_errors"])
    assert final_cleaned.read_text(encoding="utf-8") == "existing cleaned data\n"
    assert not list(final_cleaned.parent.glob(".case-1.*.tmp"))


def test_graph_does_not_overwrite_existing_cleaned_file_on_valid_rerun(tmp_path):
    _write_case(tmp_path)
    final_cleaned = tmp_path / "cleaned" / "case-1.csv"
    final_cleaned.parent.mkdir()
    final_cleaned.write_text("existing cleaned data\n", encoding="utf-8")

    state = build_generation_graph(tmp_path, FakeClient(), set()).invoke({"case_id": "case-1"})

    assert state["review_status"] == "needs_revision"
    assert any("already exists" in error for error in state["validation_errors"])
    assert final_cleaned.read_text(encoding="utf-8") == "existing cleaned data\n"
    assert not list(final_cleaned.parent.glob(".case-1.*.tmp"))
