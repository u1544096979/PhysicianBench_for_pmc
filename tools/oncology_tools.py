"""OncoBench v1 考生工具层（17工具）.

spec: docs/superpowers/specs/2026-08-20-oncobench-eval-loop-v1.md §4
- 14类别查询一一对齐 + query_keyword + query_date_range + write_file
- 过滤只有 category + 日期（E1/E2）；日期 start_date/end_date ISO含端点（E8）
- 返回50行截断；空结果友好提示；write_file限output/前缀
- case_id 由 OncologyToolkit 构造时注入，不暴露给模型
"""
from __future__ import annotations

import re
from pathlib import Path

MAX_ROWS = 50
OUTPUT_DIR_NAME = "output"

# 14类别 → 工具名（一一对齐，E2）
CATEGORY_TOOL_MAP: dict[str, str] = {
    "诊断": "query_diagnosis",
    "病理": "query_pathology",
    "影像": "query_imaging",
    "用药": "query_medication",
    "检验": "query_lab",
    "病史": "query_history",
    "查体": "query_physical_exam",
    "手术": "query_surgery",
    "病程": "query_course",
    "入院": "query_admission",
    "出院": "query_discharge",
    "会诊": "query_consultation",
    "评估": "query_assessment",
    "不良反应": "query_adverse_event",
}
TOOL_CATEGORY_MAP: dict[str, str] = {v: k for k, v in CATEGORY_TOOL_MAP.items()}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class OncologyToolkit:
    """绑定单个 case（清洗后CSV）的考生工具集.

    用法:
        kit = OncologyToolkit(case_id, cleaned_csv_path, work_dir)
        kit.get_tool_functions()   # {工具名: 函数} 给MiniAgent注册
        kit.call_log               # [(工具名, 参数dict, 返回预览)] 供data_retrieval判分
    """

    def __init__(self, case_id: str, cleaned_csv: Path, work_dir: Path):
        self.case_id = case_id
        self.cleaned_csv = Path(cleaned_csv)
        self.work_dir = Path(work_dir)
        self.output_dir = self.work_dir / OUTPUT_DIR_NAME
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.call_log: list[dict] = []
        self._events = self._load_events()

    # ------------------------------------------------------------------
    # 数据加载与过滤
    # ------------------------------------------------------------------

    def _load_events(self) -> list[dict[str, str]]:
        import csv as _csv

        events: list[dict[str, str]] = []
        with self.cleaned_csv.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = _csv.DictReader(fh)
            for row_number, row in enumerate(reader, start=2):
                ev = {k: (row.get(k) or "") for k in (
                    "event_date", "category", "feature_name", "value",
                    "actual_value", "extra_value", "unit", "method", "subject",
                )}
                ev["_source_row"] = str(row_number)
                events.append(ev)
        events.sort(key=lambda e: (e["event_date"], e["_source_row"]))
        return events

    @staticmethod
    def _validate_date(name: str, value) -> None:
        if value is None or value == "":
            return
        value = str(value).strip()
        if not _DATE_RE.match(value):
            raise ValueError(
                f"{name} 格式应为 YYYY-MM-DD（如 2021-08-01），收到: {value!r}"
            )

    def _filter(
        self,
        category: str | None,
        start_date,
        end_date,
    ) -> list[dict[str, str]]:
        self._validate_date("start_date", start_date)
        self._validate_date("end_date", end_date)
        start = (str(start_date).strip() if start_date else None) or None
        end = (str(end_date).strip() if end_date else None) or None
        out = []
        for ev in self._events:
            if category is not None and ev["category"] != category:
                continue
            d = ev["event_date"]
            if start and d < start:
                continue
            if end and d > end:
                continue
            out.append(ev)
        return out

    # ------------------------------------------------------------------
    # 返回渲染
    # ------------------------------------------------------------------

    @staticmethod
    def _render_event(ev: dict[str, str]) -> str:
        head = f"[{ev['_source_row']}] {ev['event_date']} [{ev['category']}] {ev['feature_name']}: {ev['value']}"
        tails = []
        if ev.get("actual_value"):
            tails.append(f"实际值:{ev['actual_value']}")
        if ev.get("extra_value"):
            tails.append(str(ev["extra_value"]))
        if ev.get("method"):
            tails.append(f"方法:{ev['method']}")
        if ev.get("unit"):
            tails.append(f"单位:{ev['unit']}")
        if tails:
            head += " (" + "; ".join(tails) + ")"
        return head

    def _render_rows(self, rows: list[dict[str, str]], empty_hint: str) -> str:
        if not rows:
            return empty_hint
        lines = [self._render_event(ev) for ev in rows[:MAX_ROWS]]
        if len(rows) > MAX_ROWS:
            lines.append(
                f"（共{len(rows)}条，已显示前{MAX_ROWS}条。建议用 start_date/end_date 缩小范围）"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 工具实现
    # ------------------------------------------------------------------

    def _category_tool(self, category: str):
        def _query(start_date: str | None = None, end_date: str | None = None) -> str:
            """按类别查询病例事件（可选日期范围，ISO格式 YYYY-MM-DD，含端点）."""
            rows = self._filter(category, start_date, end_date)
            self.call_log.append({
                "tool": CATEGORY_TOOL_MAP[category],
                "args": {"start_date": start_date, "end_date": end_date},
                "category": category,
                "n_rows": len(rows),
            })
            return self._render_rows(
                rows, f"【{category}】类在指定范围内无记录。",
            )
        _query.__name__ = CATEGORY_TOOL_MAP[category]
        _query.__doc__ = f"查询该患者【{category}】类全部事件。可选参数: start_date/end_date（YYYY-MM-DD）。"
        return _query

    def query_keyword(self, keyword: str) -> str:
        """在全部事件的 字段名/值/补充值 中做关键词全文检索（不区分大小写）."""
        if not keyword or not str(keyword).strip():
            return "keyword 不能为空。"
        kw = str(keyword).strip().casefold()
        rows = [
            ev for ev in self._events
            if kw in ev["feature_name"].casefold()
            or kw in ev["value"].casefold()
            or kw in ev["extra_value"].casefold()
        ]
        self.call_log.append({
            "tool": "query_keyword", "args": {"keyword": keyword},
            "category": None, "n_rows": len(rows),
        })
        return self._render_rows(rows, f"未找到与“{keyword}”相关的事件。")

    def query_date_range(self, start_date: str, end_date: str) -> str:
        """按时间窗查询全部类别的 events（ISO格式 YYYY-MM-DD，含端点）."""
        rows = self._filter(None, start_date, end_date)
        self.call_log.append({
            "tool": "query_date_range",
            "args": {"start_date": start_date, "end_date": end_date},
            "category": None, "n_rows": len(rows),
        })
        return self._render_rows(
            rows, f"{start_date} 至 {end_date} 范围内无记录。",
        )

    def write_file(self, path: str, content: str) -> str:
        """将文本写入工作区文件（仅允许 output/ 目录下的相对路径）."""
        rel = str(path or "").strip().lstrip("/")
        if ".." in Path(rel).parts or Path(rel).is_absolute() or not rel.startswith("output/"):
            return "写入失败：path 必须是 output/ 开头的相对路径（如 output/diagnosis_report.md）。"
        target = self.work_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        self.call_log.append({
            "tool": "write_file", "args": {"path": rel, "chars": len(str(content))},
            "category": None, "n_rows": 0,
        })
        return f"已写入 {rel}（{len(str(content))} 字符）。"

    def read_report(self, rel: str = "output/diagnosis_report.md") -> str:
        """判分侧读取考生最终报告（不注册给模型）."""
        target = self.work_dir / rel
        if not target.exists():
            return ""
        return target.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def get_tool_functions(self) -> dict:
        tools: dict = {}
        for category in CATEGORY_TOOL_MAP:
            tool = self._category_tool(category)
            tools[tool.__name__] = tool
        tools["query_keyword"] = self.query_keyword
        tools["query_date_range"] = self.query_date_range
        tools["write_file"] = self.write_file
        return tools

    def get_tool_specs(self) -> list[dict]:
        """OpenAI function calling 格式的工具描述（给支持该协议的模型用）."""
        specs = []
        for name in list(CATEGORY_TOOL_MAP.values()) + ["query_keyword", "query_date_range", "write_file"]:
            fn = self.get_tool_functions()[name]
            if name in TOOL_CATEGORY_MAP.values() or name.startswith("query_") and name not in ("query_keyword", "query_date_range"):
                params = {
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD（可选，含当天）"},
                        "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD（可选，含当天）"},
                    },
                }
            elif name == "query_keyword":
                params = {
                    "type": "object",
                    "properties": {"keyword": {"type": "string", "description": "检索关键词"}},
                    "required": ["keyword"],
                }
            elif name == "query_date_range":
                params = {
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
                        "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                    },
                    "required": ["start_date", "end_date"],
                }
            else:  # write_file
                params = {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "输出路径，必须 output/ 开头"},
                        "content": {"type": "string", "description": "文件内容"},
                    },
                    "required": ["path", "content"],
                }
            specs.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": (fn.__doc__ or name).strip(),
                    "parameters": params,
                },
            })
        return specs
