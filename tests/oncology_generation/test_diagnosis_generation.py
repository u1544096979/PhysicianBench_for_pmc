import csv
from pathlib import Path

from pipeline.oncology_generation.graph import build_generation_graph
from pipeline.oncology_generation.nodes import select_target_group
from pipeline.oncology_generation.schemas import EventGroup
from tools.csv_event_types import EVENT_COLUMNS


def _write_case(root: Path) -> None:
    source = root / "raw" / "csv" / "case-1.csv"
    source.parent.mkdir(parents=True)
    fields = list(EVENT_COLUMNS)
    rows = [
        {"case_id": "case-1", "group_id": "g1", "event_date": "2024-01-01", "category": "病史", "feature_name": "症状", "value": "咳嗽"},
        {"case_id": "case-1", "group_id": "g2", "event_date": "2024-01-02", "category": "病理", "feature_name": "病理诊断", "value": "肺腺癌"},
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
        assert "target_group_id" in prompt
        return type("Response", (), {"content": '{"target_group_id":"g2","selection_rationale":"明确病理诊断","role":"oncologist","instruction":"请判断诊断并说明依据。","deliverable":"诊断意见"}'})()


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
