from pipeline.oncology_generation.schemas import validate_state


def test_validation_rejects_missing_evidence_and_unknown_tools():
    state = {
        "raw_events": [{"_source_row": "2", "category": "诊断", "feature_name": "诊断名称", "value": "淋巴瘤"}],
        "task_draft": {"instruction": "Review the case."},
        "checkpoint_drafts": [{
            "kind": "retrieval", "objective": "find diagnosis", "tool_names": ["bad_tool"],
            "evidence_refs": [{"row": 99, "category": "诊断", "feature_name": "诊断名称", "value": "不存在"}],
            "verification": "trajectory", "pass_criteria": "event retrieved",
        }],
    }
    errors = validate_state(state, {"csv_search_diagnosis_events"})
    assert any("unknown tool" in error for error in errors)
    assert any("missing evidence" in error for error in errors)


def test_validation_accepts_supported_checkpoint_with_evidence():
    state = {
        "raw_events": [{"_source_row": "2", "category": "诊断", "feature_name": "诊断名称", "value": "淋巴瘤"}],
        "task_draft": {"instruction": "Review the case."},
        "checkpoint_drafts": [{
            "kind": "retrieval", "objective": "find diagnosis", "tool_names": ["csv_search_diagnosis_events"],
            "evidence_refs": [{"row": 2, "category": "诊断", "feature_name": "诊断名称", "value": "淋巴瘤"}],
            "verification": "trajectory", "pass_criteria": "event retrieved",
        }],
    }
    assert validate_state(state, {"csv_search_diagnosis_events"}) == []
