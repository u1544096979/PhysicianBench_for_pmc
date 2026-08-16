import csv
from pathlib import Path

from pipeline.oncology_generation.schemas import EventGroup, validate_state


def _event(row: str, group_id: str, feature_name: str, value: str, category: str = "病理"):
    return {"_source_row": row, "group_id": group_id, "event_date": "2024-01-01", "category": category, "feature_name": feature_name, "value": value}


def _state(tmp_path: Path, instruction: str = "请判断患者的诊断并说明依据。"):
    target_events = [_event("3", "g2", "病理诊断", "肺腺癌")]
    cleaned = tmp_path / "cleaned" / "case.csv"
    cleaned.parent.mkdir()
    with cleaned.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["group_id", "feature_name", "value"])
        writer.writeheader()
        writer.writerow({"group_id": "g1", "feature_name": "症状", "value": "咳嗽"})
    return {
        "raw_events": [_event("2", "g1", "症状", "咳嗽", "病史"), *target_events, _event("4", "g3", "治疗", "手术", "手术")],
        "event_groups": [
            EventGroup("g1", "2024-01-01", 2, "病史", [_event("2", "g1", "症状", "咳嗽", "病史")]),
            EventGroup("g2", "2024-01-01", 3, "病理", target_events),
            EventGroup("g3", "2024-01-01", 4, "手术", [_event("4", "g3", "治疗", "手术", "手术")]),
        ],
        "target_group_id": "g2", "target_events": target_events,
        "task_draft": {"instruction": instruction}, "cleaned_path": cleaned,
    }


def test_validation_accepts_diagnostic_feature_in_non_diagnosis_category(tmp_path):
    assert validate_state(_state(tmp_path)) == []


def test_validation_rejects_missing_target_and_untraceable_events(tmp_path):
    state = _state(tmp_path)
    state["target_group_id"] = "missing"
    state["target_events"] = [_event("99", "g2", "病理诊断", "肺腺癌")]
    errors = validate_state(state)
    assert any("target group" in error for error in errors)
    assert any("trace" in error for error in errors)


def test_validation_rejects_cleaned_target_following_groups_and_answer_leak(tmp_path):
    state = _state(tmp_path, instruction="患者的诊断是肺腺癌，请复核。")
    with state["cleaned_path"].open("a", encoding="utf-8") as stream:
        stream.write("g3,治疗,手术\n")
    errors = validate_state(state)
    assert any("cleaned" in error and "group" in error for error in errors)
    assert any("instruction" in error and "value" in error for error in errors)


def test_validation_rejects_output_outside_cleaned_directory(tmp_path):
    state = _state(tmp_path)
    state["cleaned_path"] = tmp_path / "raw" / "case.csv"
    assert any("cleaned directory" in error for error in validate_state(state))
