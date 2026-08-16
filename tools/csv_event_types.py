"""Shared types and constants for oncology CSV event queries."""

from __future__ import annotations

from dataclasses import dataclass

SUPPORTED_CATEGORIES = (
    "入院", "病史", "诊断", "检验", "影像", "病理", "手术", "用药",
    "病程", "评估", "不良反应", "出院", "会诊", "其他",
)

EVENT_COLUMNS = (
    "case_id", "encnt_no", "group_id", "subject", "feature_name",
    "feature_type", "value", "actual_value", "extra_value", "unit",
    "method", "source", "_record_source", "event_date", "category",
    "pipeline_version",
)


@dataclass(frozen=True)
class EventQuery:
    case_id: str
    category: str | None = None
    subject: str | None = None
    feature_name: str | None = None
    event_date: str | None = None
    group_id: str | None = None
    limit: int = 100

    def validate(self) -> None:
        if not self.case_id or self.case_id != self.case_id.strip() or "/" in self.case_id or "\\" in self.case_id:
            raise ValueError("case_id must be a non-empty filename stem")
        if self.category is not None and self.category not in SUPPORTED_CATEGORIES:
            raise ValueError(f"Unsupported category: {self.category}")
        if self.limit <= 0:
            raise ValueError("limit must be positive")
