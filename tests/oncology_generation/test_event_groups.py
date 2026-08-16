from pipeline.oncology_generation.nodes import build_event_groups


def _event(row: str, group_id: str, date: str, category: str, value: str) -> dict[str, str]:
    return {
        "_source_row": row,
        "group_id": group_id,
        "event_date": date,
        "category": category,
        "feature_name": "诊断名称",
        "value": value,
    }


def test_build_event_groups_preserves_source_first_occurrence_and_all_rows():
    events = [
        _event("10", "g2", "2024-01-02", "诊断", "B"),
        _event("11", "g2", "2024-01-02", "诊断", "B-分期"),
        _event("12", "g1", "2024-01-01", "诊断", "A"),
        _event("13", "g3", "2024-01-02", "病理", "C"),
    ]

    groups = build_event_groups(events)

    assert [group.group_id for group in groups] == ["g2", "g1", "g3"]
    assert groups[0].event_date == "2024-01-02"
    assert groups[0].first_source_row == 10
    assert groups[0].category == "诊断"
    assert groups[0].events == events[:2]
