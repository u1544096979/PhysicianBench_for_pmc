"""schemas / task_types / 字面泄漏检测 单元测试."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.oncology_generation.schemas import (  # noqa: E402
    TASK_TYPE_VALUES,
    CHECKPOINT_LAYERS,
    EventGroup,
    TaskDraft,
    build_event_groups,
    serialize_groups,
)
from pipeline.oncology_generation.task_types import TASK_TYPES, format_task_type_catalog  # noqa: E402
from pipeline.oncology_generation import nodes as N  # noqa: E402


def _mk_groups():
    g1 = EventGroup(
        group_id="aaaa1111", date="2018-03-01", category="病理",
        events=[
            {"feature_name": "病理诊断", "value": "浸润性导管癌", "extra_value": ""},
            {"feature_name": "免疫组化", "value": "HER2 3+", "extra_value": ""},
        ],
    )
    g2 = EventGroup(
        group_id="bbbb2222", date="2018-11-26", category="诊断",
        events=[
            {"feature_name": "诊断名称", "value": "乳腺癌", "extra_value": ""},
            {"feature_name": "临床分期", "value": "pT2N1M0", "extra_value": ""},
        ],
    )
    return [g1, g2]


def test_task_types_complete():
    assert set(TASK_TYPES.keys()) == set(TASK_TYPE_VALUES)
    for t in TASK_TYPES.values():
        assert t.label and t.applicability and t.instruction_template
        assert "{target_date}" in t.instruction_template
    catalog = format_task_type_catalog()
    for code in TASK_TYPE_VALUES:
        assert code in catalog


def test_checkpoint_layers():
    assert set(CHECKPOINT_LAYERS) == {
        "data_retrieval", "clinical_reasoning", "outcome_check", "documentation",
    }


def test_serialize_groups_summary_and_full():
    groups = _mk_groups()
    summary = serialize_groups(groups, full=False)
    full = serialize_groups(groups, full=True)
    assert "aaaa1111" in summary and "2018-03-01" in summary
    assert "浸润性导管癌" not in summary  # 摘要不带值
    assert "浸润性导管癌" in full
    assert "HER2 3+" in full


def test_build_event_groups_from_events():
    events = [
        {"group_id": "g1", "event_date": "2018-03-01", "category": "病理",
         "feature_name": "病理诊断", "value": "浸润性导管癌", "extra_value": "", "_source_row": "1"},
        {"group_id": "g1", "event_date": "", "category": "",
         "feature_name": "免疫组化", "value": "HER2 3+", "extra_value": "", "_source_row": "2"},
        {"group_id": "g2", "event_date": "2018-11-26", "category": "诊断",
         "feature_name": "临床分期", "value": "pT2N1M0", "extra_value": "", "_source_row": "3"},
    ]
    groups = build_event_groups(events)
    assert len(groups) == 2
    assert groups[0].group_id == "g1"
    assert groups[0].date == "2018-03-01"
    assert groups[0].category == "病理"
    assert len(groups[0].events) == 2


def test_visible_groups_truncation():
    groups = _mk_groups()
    visible = N.visible_groups(groups, "bbbb2222")
    assert [g.group_id for g in visible] == ["aaaa1111"]
    with pytest.raises(ValueError):
        N.visible_groups(groups, "notexist")


def test_literal_leak_check():
    groups = _mk_groups()
    visible = [groups[0]]
    draft_clean = TaskDraft(
        task_type="T1_staging", target_group_id="bbbb2222", target_date="2018-11-26",
        instruction="请根据病理和影像判定肿瘤分期。",
        deliverable="output/diagnosis_report.md",
        ground_truth={"stage": "pT2N1M0"}, rationale="r",
    )
    assert N.literal_leak_check(draft_clean, visible) is None

    draft_leak_instr = TaskDraft(
        task_type="T1_staging", target_group_id="bbbb2222", target_date="2018-11-26",
        instruction="请判断分期是否为pT2N1M0。",
        deliverable="output/diagnosis_report.md",
        ground_truth={"stage": "pT2N1M0"}, rationale="r",
    )
    leak = N.literal_leak_check(draft_leak_instr, visible)
    assert leak and "pT2N1M0" in leak

    # 可见轨迹中包含答案值（截断点之前已有同样记录）也算泄漏
    visible_dup = _mk_groups()  # g1里没有；构造一个值在前的场景
    dup_g = EventGroup(group_id="cccc3333", date="2018-05-01", category="诊断",
                       events=[{"feature_name": "临床分期", "value": "pT2N1M0"}])
    leak2 = N.literal_leak_check(draft_clean, [dup_g])
    assert leak2 is not None
