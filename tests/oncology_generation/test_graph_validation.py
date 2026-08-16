import csv
from copy import deepcopy
from pathlib import Path

import pytest

from pipeline.oncology_generation.leakage import diagnostic_fragments
from pipeline.oncology_generation.schemas import EventGroup, validate_state


def _event(row: str, group_id: str, feature_name: str, value: str, category: str = "病理"):
    return {
        "_source_row": row, "group_id": group_id, "event_date": "2024-01-01", "category": category,
        "feature_name": feature_name, "value": value, "subject": "患者A", "feature_type": "文本",
        "actual_value": value, "extra_value": "extra", "unit": "", "method": "病理检查",
        "source": "病理报告", "_record_source": "fixture", "pipeline_version": "v1",
    }


def _state(
    tmp_path: Path,
    instruction: str = "请判断患者的诊断并说明依据。",
    target_value: str = "肺腺癌",
):
    target_events = [_event("3", "g2", "病理诊断", target_value)]
    cleaned = tmp_path / "cleaned" / "case.csv"
    cleaned.parent.mkdir()
    with cleaned.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["group_id", "feature_name", "value"])
        writer.writeheader()
        writer.writerow({"group_id": "g1", "feature_name": "症状", "value": "咳嗽"})
    return {
        "data_root": tmp_path,
        "raw_events": [_event("2", "g1", "症状", "咳嗽", "病史"), *target_events, _event("4", "g3", "治疗", "手术", "手术")],
        "event_groups": [
            EventGroup("g1", "2024-01-01", 2, "病史", [_event("2", "g1", "症状", "咳嗽", "病史")]),
            EventGroup("g2", "2024-01-01", 3, "病理", deepcopy(target_events)),
            EventGroup("g3", "2024-01-01", 4, "手术", [_event("4", "g3", "治疗", "手术", "手术")]),
        ],
        "target_group_id": "g2", "target_events": target_events,
        "task_draft": {
            "selection_rationale": "病理结果明确",
            "role": "oncologist",
            "instruction": instruction,
            "deliverable": "诊断意见",
        },
        "cleaned_path": cleaned,
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


def test_validation_rejects_case_insensitive_answer_leak(tmp_path):
    state = _state(tmp_path, instruction="The likely stage is iiia.")
    state["event_groups"][1].events[0]["value"] = "IIIA"
    state["target_events"][0]["value"] = "IIIA"
    state["raw_events"][1]["value"] = "IIIA"

    errors = validate_state(state)

    assert any("instruction" in error and "value" in error for error in errors)


def test_validation_rejects_diagnostic_fragment_leak(tmp_path):
    state = _state(
        tmp_path,
        instruction="请根据现有资料判断是否为肺腺癌。",
        target_value="病理提示肺腺癌，结合临床",
    )

    errors = validate_state(state)

    assert any("instruction" in error and "value" in error for error in errors)


def test_validation_ignores_non_diagnostic_short_fragments(tmp_path):
    state = _state(
        tmp_path,
        instruction="请考虑癌症可能并给出下一步建议。",
        target_value="考虑，癌",
    )

    assert validate_state(state) == []


def test_diagnostic_fragment_minimum_rules():
    assert diagnostic_fragments("病理提示肺腺癌，结合临床") == ("肺腺癌",)
    assert diagnostic_fragments("病理提示：肺腺癌（结合临床）") == ("肺腺癌",)
    for separator in "|=:/\\":
        assert diagnostic_fragments(f"病理提示{separator}肺腺癌{separator}结合临床") == ("肺腺癌",)
    assert diagnostic_fragments("IIIA") == ("iiia",)
    assert diagnostic_fragments("癌，abc，结合临床") == ()


def test_validation_rejects_ascii_delimited_diagnostic_fragment(tmp_path):
    state = _state(
        tmp_path,
        instruction="请判断是否为肺腺癌。",
        target_value="病理提示|肺腺癌|结合临床",
    )

    errors = validate_state(state)

    assert any("instruction" in error and "value" in error for error in errors)


def test_validation_rejects_output_outside_cleaned_directory(tmp_path):
    state = _state(tmp_path)
    external_cleaned = tmp_path / "external" / "cleaned"
    external_cleaned.mkdir(parents=True)
    state["cleaned_path"] = external_cleaned / "case.csv"
    state["cleaned_path"].write_text("group_id\n", encoding="utf-8")
    assert any("cleaned directory" in error for error in validate_state(state))


def test_validation_rejects_target_event_with_rewritten_original_field(tmp_path):
    state = _state(tmp_path)
    state["target_events"] = deepcopy(state["target_events"])
    state["target_events"][0]["subject"] = "被改写患者"

    errors = validate_state(state)

    assert any("trace" in error for error in errors)


@pytest.mark.parametrize("missing", ["selection_rationale", "role", "instruction", "deliverable"])
def test_validation_rejects_task_draft_missing_required_field(tmp_path, missing):
    state = _state(tmp_path)
    del state["task_draft"][missing]

    errors = validate_state(state)

    assert any(missing in error for error in errors)
