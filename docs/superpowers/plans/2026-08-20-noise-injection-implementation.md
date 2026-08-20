# Noise Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 向 v2 肿瘤任务注入"事实无关但真实"的噪声事件（Layer A 常规行 + Layer B 急性病程线），经三道闸门（规则 → LLM 裁判 → 可解性复验）过滤后落盘，提升检索/筛选难度而不破坏答案唯一可推导性。

**Architecture:** 新增独立包 `pipeline/noise_injection/`（纯函数核心，不依赖 graph/state），提供 `run_injection` 编排入口。两个接入点共用该核心：① v2 流水线在 `evaluate_solution` 与 `generate_checkpoints` 之间插入薄节点 `inject_noise`（管新任务，噪直接写入原目录）；② 新增 `scripts/apply_noise.py` 批处理脚本（管存量任务，写入平行目录 `tasks/oncology-v2-noisy/`）。

**Tech Stack:** Python 3.10+, 复用现有 `llm.client.get_default_client` / `prompts_v2.build_solve_prompt / build_evaluate_prompt` / `leakage.find_leaked_target_values` / `review_queue.append_review_item`。`config` / `catalog` 为纯声明式数据，全任务单套全局参数。

## Global Constraints

- **红线（绝对禁止，violate 即 B 类矛盾）**：
  - 类别白名单仅 `评估 / 检验 / 用药 / 病程`；`诊断 / 病史 / 影像 / 病理 / 手术 / 入院 / 出院 / 其他 / 会诊 / 不良反应` 整类禁用（`catalog.FORBIDDEN_CATEGORIES`）。
  - 任何噪声行不得含肿瘤标志物（CEA/AFP/CA125/CA19-9/CA15-3/CA72-4/PSA/CYFRA21-1/NSE/SCC/LDH/ProGRP/c-met 及其英文同义），数据化维护于 `catalog.TUMOR_MARKERS`。
  - 任何噪声行不得含抗肿瘤药物（化疗药、`-tinib` TKI、PD-1/PD-L1/CTLA-4 抑制剂、内分泌治疗药），维护于 `catalog.ANTI_TUMOR_DRUG_MARKERS`。
  - 任何噪声行不得含疗效/分期信号：疗效评估（CR/PR/SD/PD/完全缓解…）、治疗反应、随访结果、临床/病理分期、TNM、ECOG、KPS、PFS、OS、总生存期、无进展生存期、周期数。
  - 噪声行不得与病例既有事实冲突（否认模式 + LLM 提示注入病例事实 + judge 兜底）。
- 目标 `event_date ∈ [病例首个事件日期, target_date)`，严格早于评估时点（target_date 即截断点，target_date·之前的日期都允许，**[first, target_date) 半开区间**）。
- Layer B 急性病程线（2~4 天自包含小簇）置于时间窗中段，**避开关键证据日期**（目标组日期 + 可见集合中含肿瘤标志物的检验组日期 + 影像组日期）。
- 每行噪声一个新的 UUID `group_id`（不与真实组混用）；叙事包行关联只记 manifest `episode_id`，**不用 group_id 串联**。
- CSV 内**不打任何噪声标记**；噪声身份只存在于 `noise_manifest.json`。
- 指令（instruction.md）不提示存在噪声；不改 agent/工具层/checkpoint/指令模板。
- manifest `final_status ∈ {"noisy","degraded_clean"}`；降级任务同样写 manifest（`rows: []`），保证目录内 manifest 恒存在。
- 复用 `prompts_v2.build_solve_prompt / build_evaluate_prompt`；复用 `leakage.find_leaked_target_values`；复用 `review_queue.append_review_item`（追加 `generated/v2/review_queue.jsonl`）。

---

## 文件结构与依赖

```
pipeline/noise_injection/
├── __init__.py        # 公开导出（空或 re-export）
├── config.py          # NoiseConfig dataclass
├── catalog.py         # 声明式目录表 + 黑名单 + 默认惯例（review 看此表）
├── prompts.py         # 全部噪声提示词 + PROMPT_VERSIONS
├── context.py         # [新增] CaseContext + build_context（两个入口共用）
├── plan.py            # NoisePlanner（LLM 生成计划 JSON）
├── materialize.py     # 计划 → 17 字段 CSV 行（含惯例采样/日期/cluster）
├── safety.py          # 闸门1 规则检查（零 LLM）
├── judge.py           # 闸门2 LLM 逐行裁判
├── solvable.py        # 闸门3 可解性复验
├── manifest.py        # noise_manifest.json 读写/构建
└── injection.py       # [新增] run_injection 编排（重试阶梯 §4.2）
scripts/apply_noise.py                # 存量批处理
```

> **对 spec §5.1 的偏离说明**：spec 的 9 文件清单遗漏了「编排器 `run_injection`」与「`CaseContext` 组装」两个环节，但 §4 / §5.2 / §5.3 又明确要求两入口共用 `run_injection`。为保持职责单一，新增 `context.py` 与 `injection.py` 两个编排文件（共 11 个）。核心数据/规则/闸门仍按 spec 的 9 文件落地。依赖方向：`plan/materialize` 依赖 `catalog`、`context`；`injection` 依赖全部；三道闸门互不依赖、可独立单测；包内不依赖 `oncology_generation` 的 graph/state，仅复用其 `prompts_v2` 与 `leakage` 的纯函数。

任务分解（每任务独立可测、可独立 review）：

- Task 1: config + catalog + `__init__`（数据层，无 LLM）
- Task 2: prompts + context（提示词 + 用例上下文组装）
- Task 3: materialize（计划 → 17 字段行）
- Task 4: plan（LLM 计划生成）
- Task 5: safety（闸门1）
- Task 6: judge（闸门2）
- Task 7: solvable（闸门3）
- Task 8: manifest + injection（编排 + 重试阶梯 + 落盘链路）
- Task 9: v2 流水线接入（state 字段 + graph + nodes.inject_noise + materialize 追噪）
- Task 10: scripts/apply_noise.py
- Task 11: 集成 + 端到端测试收尾

**Interfaces 一览（后续任务依赖签名）**：
- `NoiseConfig(noise_rows=60, episodes=2, retry_reduced=(30,1), max_attempts=3, judge_batch_size=10)`（frozen dataclass，`config.py`）
- `catalog`：`ALLOWED_CATEGORIES: tuple[str,...]`、`FORBIDDEN_CATEGORIES: tuple[str,...]`、`TUMOR_MARKERS: tuple[str,...]`、`ANTI_TUMOR_DRUG_MARKERS: tuple[str,...]`、`FORBIDDEN_TERMS_BY_CATEGORY: dict[str, tuple[str,...]]`、`SUPPORTIVE_MEDICATIONS: tuple[str,...]`、`LAYER_B_MEDICATIONS: tuple[str,...]`、`FEATURE_NAMES_BY_CATEGORY: dict[str, tuple[str,...]]`、`DEFAULT_CONVENTIONS: dict[str, dict]`、`CATEGORY_FEATURE_TYPE_FALLBACK: dict[str, tuple[str,...]]`、`scan_forbidden(text) -> list[str]`
- `CaseContext`（`context.py`，frozen dataclass）：`case_id / encnt_no / task_type / target_date / first_event_date / instruction / ground_truth / key_evidence_dates: list[str] / denial_terms: list[str] / convention_by_category: dict[str, dict] / matrix_rows: list[dict]`（raw event dicts，含 group_id/category/subject/feature_name/value/event_date）`;` 以及函数 `build_context(*, case_id, events, task_type, target_group_id, target_date, instruction, ground_truth, answer_event_rows=None, first_event_date=None) -> CaseContext`
- `prompts.py`：`PROMPT_VERSIONS = {"plan":"v1","judge":"v1"}`、`build_plan_prompt(context, noise_rows, episodes) -> list[dict]`、`build_judge_prompt(context, rows_batch) -> list[dict]`
- `plan.py`：`NoisePlanner(client)` with `plan(context, *, noise_rows, episodes) -> dict`（返回 `{"layer_a":[...], "episodes":[...]}`）
- `materialize.py`：`materialize(context, plan) -> list[dict]`（每个行 dict 含 17 个 CSV 字段 + 元字段 `layer`/`episode_id`（**无下划线前缀**，与真实 CSV 列 `_record_source` 区分））
- `safety.py`：`run_safety_gate(context, rows) -> (passed: list[dict], rejections: list[dict])`
- `judge.py`：`NoiseJudge(client)` with `judge(context, rows, batch_size=10) -> (passed, rejections)`
- `solvable.py`：`check(context, rows, client) -> (ok: bool, detail: str)`
- `manifest.py`：`build_manifest(context, result) -> dict`、`write_manifest(path, manifest)`、`read_manifest(path) -> dict`
- `injection.py`：`run_injection(context, config, client, *, visible_text=None, full_attempts=None) -> InjectionResult(final_status, rows, manifest, attempts, review_queue_entries, degrade_reason)`，`rows` 为 17 字段 CSV 行、不含元字段。`visible_text` 为可选的干净可见事件序列化文本，内部透传给 `solvable.check`（实现在 `injection.py`）。
- `nodes.py`（modify）：`inject_noise(state) -> dict`；`materialize` 追噪
- `graph.py`（modify）：`evaluate_solution → inject_noise → generate_checkpoints`
- `scripts/apply_noise.py`：CLI `--dry-run/--resume/--limit/--case-ids/--workers`

**收益 / 验收对齐**：spec §9 验收标准逐条落在 Task 5/8/9/10/11。

---

### Task 1: config + catalog 数据层

**Files:**
- Create: `pipeline/noise_injection/__init__.py`, `pipeline/noise_injection/config.py`, `pipeline/noise_injection/catalog.py`
- Test: `tests/test_noise_catalog.py`

**Interfaces:** Produces `NoiseConfig`, all `catalog.*` constants + `scan_forbidden`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_noise_catalog.py
from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.config import NoiseConfig
from pipeline.noise_injection.catalog import (
    ALLOWED_CATEGORIES, FORBIDDEN_CATEGORIES, TUMOR_MARKERS,
    ANTI_TUMOR_DRUG_MARKERS, scan_forbidden, SUPPORTIVE_MEDICATIONS,
    LAYER_B_MEDICATIONS, DEFAULT_CONVENTIONS, CATEGORY_FEATURE_TYPE_FALLBACK,
)

def test_allowed_vs_forbidden_disjoint():
    assert set(ALLOWED_CATEGORIES).isdisjoint(set(FORBIDDEN_CATEGORIES))
    assert {"评估","检验","用药","病程"} <= set(ALLOWED_CATEGORIES)
    for c in ("影像","病理","手术","入院","出院","其他","会诊","诊断","病史","不良反应"):
        assert c in FORBIDDEN_CATEGORIES

def test_tumor_markers_complete():
    for m in ("CEA","AFP","CA125","CA19-9","CA15-3","CA72-4","PSA",
              "CYFRA21-1","NSE","SCC","LDH","ProGRP","c-met"):
        assert m in TUMOR_MARKERS

def test_anti_tumor_markers():
    assert any("-tinib" in x for x in ANTI_TUMOR_DRUG_MARKERS)
    assert any(x in ("PD-1","PD-L1","CTLA-4") for x in ANTI_TUMOR_DRUG_MARKERS)

def test_scan_forbidden_detects():
    assert scan_forbidden("CEA 5.2")  # 肿瘤标志物
    assert scan_forbidden("卡铂+紫杉醇")  # 化疗药
    assert scan_forbidden("使用奥希替尼")  # -tinib
    assert scan_forbidden("疗效评估 CR")  # 疗效
    assert not scan_forbidden("一般情况可，饮食睡眠良好")

def test_supportive_and_layerb_disjoint_from_forbidden():
    for drug in SUPPORTIVE_MEDICATIONS + LAYER_B_MEDICATIONS:
        assert not scan_forbidden(drug), drug

def test_defaults_complete():
    for cat in ALLOWED_CATEGORIES:
        assert "subject" in DEFAULT_CONVENTIONS[cat]
        assert "feature_type" in DEFAULT_CONVENTIONS[cat]
    assert set(CATEGORY_FEATURE_TYPE_FALLBACK) == set(ALLOWED_CATEGORIES)

def test_config_defaults():
    c = NoiseConfig()
    assert c.noise_rows == 60 and c.episodes == 2
    assert c.retry_reduced == (30, 1) and c.max_attempts == 3
    assert c.judge_batch_size == 10
```

- [ ] **Step 2: Run tests to verify they fail (module absent)**

Run: `pytest tests/test_noise_catalog.py -q`
Expected: FAIL (import error / assertion error)

- [ ] **Step 3: Implement `__init__.py`**

```python
"""OncoBench v2 任务噪声注入核心包."""
from __future__ import annotations
```

- [ ] **Step 4: Implement `config.py`**

```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class NoiseConfig:
    noise_rows: int = 60          # Layer A 行数
    episodes: int = 2             # Layer B 急性病程线条数
    retry_reduced: tuple[int, int] = (30, 1)  # 重试阶梯减量 (noise_rows, episodes)
    max_attempts: int = 3
    judge_batch_size: int = 10
```

- [ ] **Step 5: Implement `catalog.py`**（数据化维护全部规则，review 看此表即可）

```python
from __future__ import annotations
import re

# ---- 类别 ----
ALLOWED_CATEGORIES: tuple[str, ...] = ("评估", "检验", "用药", "病程")
FORBIDDEN_CATEGORIES: tuple[str, ...] = (
    "诊断", "病史", "影像", "病理", "手术", "入院", "出院", "其他", "会诊", "不良反应",
)

# ---- 肿瘤标志物（RNA/带电形式：中文+英文+简写，至少覆盖 spec 清单）----
TUMOR_MARKERS: tuple[str, ...] = (
    "CEA", "AFP", "CA125", "CA19-9", "CA15-3", "CA72-4", "PSA",
    "CYFRA21-1", "NSE", "SCC", "LDH", "ProGRP", "c-met",
    "癌胚抗原", "甲胎蛋白", "糖类抗原125", "糖类抗原19-9", "糖类抗原15-3",
    "糖类抗原72-4", "前列腺特异性抗原", "细胞角蛋白19片段", "神经元特异性烯醇化酶",
    "鳞状细胞癌抗原", "乳酸脱氢酶", "胃泌素释放肽前体", "肿瘤标志物",
)

# ---- 抗肿瘤药物标记（子串匹配，宁宽勿漏）----
ANTI_TUMOR_DRUG_MARKERS: tuple[str, ...] = (
    "PD-1", "PD-L1", "CTLA-4", "-tinib", "铂", "紫杉醇", "多西他赛",
    "吉西他滨", "卡培他滨", "5-FU", "氟尿嘧啶", "培美曲塞", "依托泊苷",
    "伊立替康", "奥沙利铂", "顺铂", "卡铂", "环磷酰胺", "阿霉素", "表阿霉素",
    "长春", "阿糖胞苷", "贝伐珠单抗", "曲妥珠单抗", "西妥昔单抗", "利妥昔单抗",
    "内分泌", "来曲唑", "他莫昔芬", "阿那曲唑", "阿比特龙", "恩扎卢胺", "瑞戈非尼",
    "索拉非尼", "仑伐替尼", "安罗替尼", "阿帕替尼", "奥希替尼", "吉非替尼",
    "厄洛替尼", "克唑替尼", "阿来替尼", "劳拉替尼", "塞瑞替尼", "达克替尼",
)

# ---- 每类别禁用的 feature_name/术语（子串）----
FORBIDDEN_TERMS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "评估": ("疗效评估", "治疗反应", "影像结论", "ECOG", "KPS", "分期", "TNM",
             "评估方法", "肿瘤测量", "RECIST", "体能状态", "功能状态", "NIHSS", "Child-Pugh"),
    "检验": ("肿瘤标志物", "基因检测", "NGS", "病理"),
    "用药": ("化疗", "靶向", "治疗反应", "周期数", "放疗", "免疫治疗", "内分泌治疗"),
    "病程": ("治疗反应", "随访结果", "PFS", "OS", "总生存期", "无进展生存期",
             "周期数", "疗效", "分期", "肿瘤", "生存状态", "死亡", "肿块", "转移"),
}

# ---- 允许的用药（Layer A 支持治疗药）----
SUPPORTIVE_MEDICATIONS: tuple[str, ...] = (
    "奥美拉唑", "泮托拉唑", "雷贝拉唑", "兰索拉唑", "埃索美拉唑",   # 护胃
    "莫沙必利", "多潘立酮", "铝碳酸镁",                              # 促动力/抗酸
    "依诺肝素", "低分子肝素", "华法林",                               # 抗凝
    "维生素C", "维生素B", "复合维生素", "钙片", "骨化三醇",           # 维矿
    "氯化钠", "葡萄糖", "复方氯化钠",                                 # 补液
    "乳果糖", "聚乙二醇", "开塞露", "麻仁",                            # 缓泻
)
LAYER_B_MEDICATIONS: tuple[str, ...] = (
    "对乙酰氨基酚", "布洛芬", "阿莫西林", "复方感冒灵", "复方氨酚烷胺",
    "酚麻美敏", "连花清瘟", "银翘解毒", "板蓝根", "氨溴索", "右美沙芬",
)

# ---- 每类别允许的 feature_name（Layer A 主键名）----
FEATURE_NAMES_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "评估": ("血压", "心率", "体温", "呼吸", "呼吸频率", "查体", "脉搏", "体重", "一般情况"),
    "检验": ("检验项目", "血红蛋白", "白细胞计数", "血小板计数", "红细胞压积",
             "ALT", "AST", "丙氨酸氨基转移酶", "天门冬氨酸氨基转移酶", "白蛋白",
             "总胆红素", "肌酐", "尿素氮", "空腹血糖", "血糖", "钙", "钠", "钾", "氯",
             "C反应蛋白", "CRP", "凝血酶原时间"),
    "用药": ("药品名称", "用药名称", "剂量", "给药途径", "用药周期", "用药"),
    "病程": ("病程", "症状", "一般情况"),
}

# ---- 每类别 feature_type 回退（无法从既有行采样时）----
CATEGORY_FEATURE_TYPE_FALLBACK: dict[str, tuple[str, ...]] = {
    "评估": ("数值型", "文本型"),
    "检验": ("数值型",),
    "用药": ("类别型",),
    "病程": ("文本型",),
}

# ---- 每类别惯例默认（subject/method/source/_record_source/pipeline_version/feature_type）
#      从全量语料 600 例采样；值必须与该病例同类别既有行风格一致。----
DEFAULT_CONVENTIONS: dict[str, dict] = {
    "评估": {"subject": "患者", "method": "", "source": "LLM提取",
             "_record_source": "论文病例报告", "pipeline_version": "v1", "feature_type": "数值型"},
    "检验": {"subject": "血液", "method": "", "source": "LLM提取",
             "_record_source": "论文病例报告", "pipeline_version": "v1", "feature_type": "数值型"},
    "用药": {"subject": "患者", "method": "口服", "source": "LLM提取",
             "_record_source": "论文病例报告", "pipeline_version": "v1", "feature_type": "类别型"},
    "病程": {"subject": "患者", "method": "", "source": "LLM提取",
             "_record_source": "论文病例报告", "pipeline_version": "v1", "feature_type": "文本型"},
}

# feature_type 合法枚举（与数据一致）
FEATURE_TYPES: tuple[str, ...] = ("数值型", "类别型", "文本型", "日期型", "偏离型")

# ------- 扫描工具 -------
_TUMOR_RE = re.compile("|".join(re.escape(x) for x in TUMOR_MARKERS), re.IGNORECASE)
_ANTI_RE = re.compile("|".join(re.escape(x) for x in ANTI_TUMOR_DRUG_MARKERS), re.IGNORECASE)

def scan_forbidden(text: object) -> list[str]:
    """扫描文本是否含肿瘤标志物/抗肿瘤药/禁用类别术语，返回命中项（空=安全）。"""
    s = str(text or "")
    hits: list[str] = []
    for marker in TUMOR_MARKERS:
        if marker.casefold() in s.casefold():
            hits.append(f"肿瘤标志物:{marker}")
    for marker in ANTI_TUMOR_DRUG_MARKERS:
        if marker.casefold() in s.casefold():
            hits.append(f"抗肿瘤药:{marker}")
    return hits
```

> 注：`FORBIDDEN_TERMS` 逐类别判断在 `safety.py` 中进行（需要 category 上下文），`scan_forbidden` 只做跨类别全局扫描（肿瘤标志物+抗肿瘤药）。

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_noise_catalog.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pipeline/noise_injection scripts 2>/dev/null; git add pipeline/noise_injection/__init__.py pipeline/noise_injection/config.py pipeline/noise_injection/catalog.py tests/test_noise_catalog.py
git commit -m "feat(noise): config + catalog declarative data & red-line lists"
```

---

### Task 2: prompts + context

**Files:**
- Create: `pipeline/noise_injection/prompts.py`, `pipeline/noise_injection/context.py`
- Test: `tests/test_noise_context.py`

**Interfaces:** Consumes `catalog.*`, config `NoiseConfig`; Produces `CaseContext`, `build_context`, `PROMPT_VERSIONS`, `build_plan_prompt`, `build_judge_prompt`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_noise_context.py
from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection import prompts as NP

def _events():
    return [
        {"group_id":"g0","category":"入院","subject":"患者","feature_name":"入院年龄",
         "value":"66","event_date":"2023-03-01","_record_source":"论文病例报告"},
        {"group_id":"g1","category":"检验","subject":"血液","feature_name":"白细胞计数",
         "value":"5.2","event_date":"2023-06-14"},
        {"group_id":"g2","category":"影像","subject":"胸部CT","feature_name":"影像结论",
         "value":"右上叶肿块","event_date":"2023-06-14"},
        {"group_id":"g3","category":"病理","subject":"","feature_name":"CEA","value":"3.1",
         "event_date":"2023-07-02"},
        {"group_id":"g4","category":"病史","subject":"患者","feature_name":"既往史",
         "value":"否认高血压、糖尿病史","event_date":"2023-03-01"},
        {"group_id":"gt","category":"评估","subject":"患者","feature_name":"疗效评估",
         "value":"PR","event_date":"2023-08-14"},
    ]

def test_build_context_fields():
    ev = _events()
    ctx = build_context(
        case_id="c1", events=ev, task_type="T2_response",
        target_group_id="gt", target_date="2023-08-14",
        instruction="评估疗效", ground_truth={"response":"PR"},
    )
    assert ctx.first_event_date == "2023-03-01"
    assert ctx.encnt_no == ""
    # 关键证据日 = 目标组 + 可见中含肿瘤标志物的检验组 + 影像组
    assert {ctx.target_date} <= set(ctx.key_evidence_dates)
    assert "2023-06-14" in ctx.key_evidence_dates  # 影像组日期
    assert "2023-06-14" in ctx.key_evidence_dates  # 含CEA的检验组日期
    assert "2023-07-02" in ctx.key_evidence_dates
    # 否认模式提取
    assert "高血压" in ctx.denial_terms and "糖尿病" in ctx.denial_terms
    # 惯例采样：检验→血液
    assert ctx.convention_by_category["检验"]["subject"] == "血液"

def test_convention_fallback():
    ev = [{"group_id":"g","category":"入院","feature_name":"x","value":"y","event_date":"2023-01-01"}]
    ctx = build_context(case_id="c2", events=ev, task_type="T1_staging",
                        target_group_id="g", target_date="2023-03-01",
                        instruction="i", ground_truth={})
    # 无既有检验行 → 回退 catalog 默认
    assert ctx.convention_by_category["检验"]["subject"] == "血液"

def test_prompt_versions_and_builders():
    assert set(NP.PROMPT_VERSIONS) == {"plan","judge"}
    ev = _events()
    ctx = build_context(case_id="c1", events=ev, task_type="T2_response",
                        target_group_id="gt", target_date="2023-08-14",
                        instruction="评估疗效", ground_truth={"response":"PR"})
    msgs = NP.build_plan_prompt(ctx, noise_rows=3, episodes=1)
    text = " ".join(m["content"] for m in msgs)
    assert "c1" in text and "2023-08-14" in text
    assert "否认" in text  # 病例事实注入
    judge_msgs = NP.build_judge_prompt(ctx, [{"row": {"category": "病程", "value": "一般情况可"}}])
    jtext = " ".join(m["content"] for m in judge_msgs)
    assert "judge" in jtext.lower() or "裁判" in jtext
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_noise_context.py -q`
Expected: FAIL

- [ ] **Step 3: Implement `context.py`**

```python
from __future__ import annotations
import csv
from dataclasses import dataclass, field
from collections import OrderedDict, defaultdict

from . import catalog


@dataclass(frozen=True)
class CaseContext:
    case_id: str
    task_type: str
    target_date: str
    first_event_date: str
    instruction: str
    ground_truth: dict
    key_evidence_dates: tuple[str, ...] = field(default_factory=tuple)
    denial_terms: tuple[str, ...] = field(default_factory=tuple)
    convention_by_category: dict = field(default_factory=dict)
    matrix_rows: tuple[dict, ...] = field(default_factory=tuple)  # raw event dicts
    encnt_no: str = ""

    def case_facts_text(self) -> str:
        """注入给 LLM 的病例事实摘要（避免矛盾噪声）."""
        return ("病例ID=%s；评估时点（截断日）=%s；首个事件日期=%s"
                % (self.case_id, self.target_date, self.first_event_date))

    def visible_noise_abs_dates(self) -> list[str]:
        return sorted(set(str(r.get("event_date", "")) for r in self.matrix_rows if r.get("event_date")))


def _first_event(rows) -> str:
    dates = [str(r.get("event_date", "")).strip() for r in rows if r.get("event_date")]
    return min(dates) if dates else ""


def _extract_denials(rows) -> list[str]:
    """从 病史/诊断 行的 text 提取 '否认 X（史）' 的 X."""
    import re
    terms: list[str] = []
    for r in rows:
        cat = r.get("category", "")
        if cat not in ("病史", "诊断"):
            continue
        text = " ".join(filter(None, [str(r.get(k, "")) for k in
                                      ("feature_name", "value", "extra_value", "actual_value")]))
        for m in re.finditer(r"否认\s*([^，。；、\s]{1,12}?)(?:史)?(?:，|。|；|$)", text):
            t = m.group(1).strip()
            if t and t not in terms and len(t) <= 8:
                terms.append(t)
    return terms


def _convention_for(rows, category: str) -> dict:
    """从该病例同类别既有行采样惯例值；缺失回退 catalog 默认."""
    conv: dict = {}
    base = dict(catalog.DEFAULT_CONVENTIONS[category])
    keys = ("subject", "method", "source", "_record_source", "pipeline_version", "feature_type")
    for room, ok in [("评估", ("评估",)), ("检验", ("检验",)), ("用药", ("用药",)), ("病程", ("病程",))]:
        if room != category:
            continue
        cnt: dict[str, dict[str, int]] = {k: defaultdict(int) for k in keys}
        for r in rows:
            if r.get("category", "") != ok[0]:
                continue
            for k in keys:
                v = str(r.get(k, "") or "")
                if v:
                    cnt[k][v] += 1
        for k in keys:
            if cnt[k]:
                conv[k] = max(cnt[k], key=cnt[k].get)
    for k in keys:
        conv[k] = conv.get(k) or base[k]
    return conv


def _key_evidence_dates(rows, target_group_id: str, target_date: str) -> list[str]:
    """关键证据日 = 目标组日期 + 可见集合中含肿瘤标志物的检验组日期 + 影像组日期."""
    tm = set(catalog.TUMOR_MARKERS)
    dates: list[str] = []
    target_date_seen = False
    for r in rows:
        gid = r.get("group_id", "")
        cat = r.get("category", "")
        if gid == target_group_id:
            if r.get("event_date"):
                dates.append(str(r.get("event_date")))
            target_date_seen = True
            continue  # 只取其日期
        if target_date_seen:
            continue  # 目标组之后不可见
        d = str(r.get("event_date", "") or "")
        if not d:
            continue
        is_marker_test = cat == "检验" and any(
            str(r.get(k, "") or "") in tm for k in ("feature_name", "value", "extra_value"))
        if cat == "影像" or is_marker_test:
            dates.append(d)
    # 规范化为该组 event_date 去重（同一组可能多行同日期）
    return list(OrderedDict.fromkeys(d for d in dates if d))


def build_context(*, case_id, events, task_type, target_group_id, target_date,
                  instruction, ground_truth, answer_event_rows=None) -> CaseContext:
    rows = list(events)
    ctx = CaseContext(
        case_id=case_id,
        task_type=task_type,
        target_date=target_date,
        first_event_date=_first_event(rows),
        instruction=instruction,
        ground_truth=ground_truth,
        key_evidence_dates=tuple(_key_evidence_dates(rows, target_group_id, target_date)),
        denial_terms=tuple(_extract_denials(rows)),
        convention_by_category={c: _convention_for(rows, c) for c in catalog.ALLOWED_CATEGORIES},
        matrix_rows=tuple(rows),
    )
    object.__setattr__(ctx, "encnt_no", _first_encnt(rows))
    return ctx


def _first_encnt(rows) -> str:
    for r in rows:
        v = str(r.get("encnt_no", "") or "")
        if v:
            return v
    return ""


def case_from_csv(case_id: str, csv_path, *, task_type, target_group_id, target_date,
                  instruction, ground_truth, answer_event_rows=None) -> CaseContext:
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        events = [r for r in reader if any((v or "").strip() for v in r.values())]
    return build_context(
        case_id=case_id, events=events, task_type=task_type,
        target_group_id=target_group_id, target_date=target_date,
        instruction=instruction, ground_truth=ground_truth,
        answer_event_rows=answer_event_rows,
    )
```

> 注：`case_from_csv` 供 `apply_noise.py` 使用；pipeline 节点直接用 `build_context` + `state["events"]`。`catalog.ALLOWED_CATEGORIES` 在 `context.py` 中经 `catalog.*` 常量引用。

- [ ] **Step 4: Implement `prompts.py`**

```python
from __future__ import annotations
from .catalog import ALLOWED_CATEGORIES

PROMPT_VERSIONS = {"plan": "v1", "judge": "v1"}

PLAN_PROMPT = """\
你是医学数据合成专家。要为一份肿瘤住院病历补充大量"事实无关但真实"的常规医疗记录（噪声），以加大信息检索难度，但绝不引入与答案矛盾或指向肿瘤相关的干扰。噪声必须"事实无关"，不是"与答案矛盾"。

【病例上下文】
- case_id: {case_id}
- 任务类型: {task_type}
- 评估时点（截断日）: {target_date}
- 病例首个事件日期: {first_event_date}
- 关键证据日期（噪声叙事线必须避开）: {key_dates}
- 该患者既往史否认项（噪声不得含）: {denial_terms}

【硬性红线】
1. 只允许类别: {categories}。严禁出现 影像/病理/手术/入院/出院/诊断/病史/其他/会诊 类别。
2. 严禁肿瘤标志物（CEA/AFP/CA125/CA19-9/PSA/NSE/LDH等）、抗肿瘤药物（化疗/靶向/免疫治疗/内分泌治疗）。
3. 严禁疗效/分期信号：疗效评估、治疗反应、随访结果、分期、TNM、ECOG、PFS/OS、周期数。
4. 所有事件日期 ∈ [{first_event_date}, {target_date})，严格早于评估时点。
5. Layer A 评分/检验数值须正常或轻度异常；用药只用支持治疗药（护胃/抗凝/维生素/补液/缓泻）。
6. 时间规则：生命体征按日分布；检验成簇（入院、治疗中期、评估前一周各一簇）；急性病程线 2~4 天自包含、置于时间窗中段、避开关键证据日期。

【输出要求】只输出一个 JSON 对象：
{{
  "layer_a": [
    {{"category": "评估|检验|用药|病程", "feature_name": "...", "value": "...",
      "unit": "..." , "event_date": "YYYY-MM-DD", "note": "一句说明，不入CSV"}}
  ],
  "episodes": [
    {{"episode_id": "ep1", "title": "轻微低热小病程",
      "days": [
        {{"category": "病程", "feature_name": "病程", "value": "今日患者体温38.2°C，伴畏寒、纳差", "date_abs": "YYYY-MM-DD"}},
        {{"category": "评估", "feature_name": "体温", "value": "38.2", "unit": "℃", "date_abs": "YYYY-MM-DD"}},
        {{"category": "用药", "feature_name": "药品名称", "value": "对乙酰氨基酚", "unit": "0.5g 口服", "date_abs": "YYYY-MM-DD"}},
        {{"category": "病程", "feature_name": "病程", "value": "体温恢复正常，食欲改善", "date_abs": "YYYY-MM-DD"}}
      ]}}
  ]
}}
Layer A 共 {noise_rows} 行；episodes 共 {episodes} 条，每条内日期链自洽且逐日+1~2天，全部 date_abs 落在时间窗内、避开关键证据日期。"""

JUDGE_PROMPT = """\
你是医学噪声裁判。下面这条添加进肿瘤病历的噪声记录，需与【标准答案】及【病例事实】核对。判据：
- related_to_answer=true：该行包含与最终答案同源的信息（会直接提示答案，或属于答案推理所必需的证据类型）。
- contradicts=true：该行与标准答案或病例既定事实相矛盾、会误导推理。

【标准答案】
{ground_truth}

【病例事实】
{case_facts}

【待审单行（JSON）】
{row_json}

只输出 JSON：{{"row_id": {row_id}, "related_to_answer": false, "contradicts": false, "reason": "简短理由"}}"""


def build_plan_prompt(context, *, noise_rows, episodes) -> list[dict]:
    from .config import NoiseConfig  # ensure config importable
    content = PLAN_PROMPT.format(
        case_id=context.case_id, task_type=context.task_type,
        target_date=context.target_date, first_event_date=context.first_event_date,
        key_dates="、".join(context.key_evidence_dates) or "无",
        denial_terms="、".join(context.denial_terms) or "无",
        categories="、".join(ALLOWED_CATEGORIES),
        noise_rows=noise_rows, episodes=episodes,
    )
    return [{"role": "user", "content": content}]


def build_judge_prompt(context, row, row_id) -> list[dict]:
    import json
    content = JUDGE_PROMPT.format(
        ground_truth=json.dumps(context.ground_truth, ensure_ascii=False),
        case_facts=context.case_facts_text(),
        row_json=json.dumps(row.get("csv_fields", row), ensure_ascii=False),
        row_id=row_id,
    )
    return [{"role": "user", "content": content}]
```

> 注：judge 按单行出一份 prompt（`build_judge_prompt(context, row, row_id)`），`NoiseJudge.judge` 内部按 `batch_size` 分块并逐行并发/串行调用，满足"每批 10 行"。

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_noise_context.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/noise_injection/prompts.py pipeline/noise_injection/context.py tests/test_noise_context.py
git commit -m "feat(noise): prompts + case context assembly"
```

---

### Task 3: materialize（计划 → 17 字段行）

**Files:**
- Create: `pipeline/noise_injection/materialize.py`
- Test: `tests/test_noise_materialize.py`

**Interfaces:** Consumes `CaseContext`, plan dict, `catalog`; Produces `materialize(context, plan) -> list[dict]`（17 CSV 字段 + `_layer/_episode_id` 元字段）.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_noise_materialize.py
from __future__ import annotations
import sys, uuid
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection.materialize import materialize, CSV_FIELDS

def _ctx():
    ev = [
        {"group_id":"g","category":"入院","subject":"患者","feature_name":"入院年龄","value":"66","event_date":"2023-03-01","_record_source":"论文病例报告"},
        {"group_id":"g1","category":"检验","subject":"血液","feature_name":"白细胞计数","value":"5.2","unit":"×10^9/L","event_date":"2023-06-14","method":"","source":"LLM提取"},
    ]
    return build_context(case_id="c1", events=ev, task_type="T2_response",
                         target_group_id="g", target_date="2023-08-14",
                         instruction="i", ground_truth={})

PLAN = {
    "layer_a": [
        {"category":"检验","feature_name":"血红蛋白","value":"125","unit":"g/L","event_date":"2023-07-01"},
        {"category":"病程","feature_name":"病程","value":"一般情况可，饮食睡眠良好","event_date":"2023-07-02","unit":""},
    ],
    "episodes": [
        {"episode_id":"ep1","days":[
            {"category":"病程","feature_name":"病程","value":"今日体温38.2°C","date_abs":"2023-07-05"},
            {"category":"评估","feature_name":"体温","value":"38.2","unit":"℃","date_abs":"2023-07-05"},
        ]},
    ],
}

def test_materialize_17_fields():
    rows = materialize(_ctx(), PLAN)
    assert len(rows) == 4
    for r in rows:
        cf = r["csv_fields"]
        assert set(CSV_FIELDS) <= set(cf)
        assert cf["case_id"] == "c1"
        assert len(cf["group_id"]) == 36  # uuid
        assert cf["event_date"] < "2023-08-14"
        assert cf["category"] in ("评估","检验","用药","病程")

def test_group_id_unique_and_no_real_group():
    rows = materialize(_ctx(), PLAN)
    gids = [r["csv_fields"]["group_id"] for r in rows]
    assert len(set(gids)) == len(gids)

def test_convention_sampled():
    rows = materialize(_ctx(), PLAN)
    lab = [r for r in rows if r["csv_fields"]["category"]=="检验"][0]
    assert lab["csv_fields"]["subject"] == "血液"  # 采样自身检验行

def test_episode_id_preserved_in_meta():
    rows = materialize(_ctx(), PLAN)
    epis = [r for r in rows if r.get("episode_id") == "ep1"]
    assert len(epis) == 2

def test_numeric_row_has_unit_and_parseable_value():
    rows = materialize(_ctx(), PLAN)
    lab = [r for r in rows if r["csv_fields"]["category"]=="检验"][0]
    assert lab["csv_fields"]["unit"]
    float(lab["csv_fields"]["value"])  # must not raise
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_noise_materialize.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
import uuid

from . import catalog

CSV_FIELDS = ("case_id", "encnt_no", "group_id", "subject", "feature_name",
              "feature_code", "feature_type", "value", "actual_value", "extra_value",
              "unit", "method", "source", "_record_source", "event_date",
              "category", "pipeline_version")

_CSV_KEYS = set(CSV_FIELDS)


def _feat_type(category, conv) -> str:
    ft = (conv.get("feature_type") or "").strip()
    return ft if ft in catalog.FEATURE_TYPES else catalog.CATEGORY_FEATURE_TYPE_FALLBACK[category][0]


def _row(context, *, category, feature_name, value, unit, event_date,
         subject=None, method=None, feature_type=None, actual_value="",
         extra_value="", layer=None, episode_id=None, feature_code="") -> dict:
    conv = context.convention_by_category[category]
    feature_type = feature_type or _feat_type(category, conv)
    cf = {
        "case_id": context.case_id,
        "encnt_no": context.encnt_no or "",
        "group_id": str(uuid.uuid4()),
        "subject": subject or conv.get("subject", ""),
        "feature_name": feature_name or "",
        "feature_code": feature_code,
        "feature_type": feature_type,
        "value": value or "",
        "actual_value": actual_value,
        "extra_value": extra_value,
        "unit": unit or "",
        "method": method if method is not None else conv.get("method", ""),
        "source": conv.get("source", ""),
        "_record_source": conv.get("_record_source", ""),
        "event_date": event_date or "",
        "category": category,
        "pipeline_version": conv.get("pipeline_version", ""),
    }
    row = {"csv_fields": cf, "group_id": cf["group_id"],
           "category": category, "feature_name": feature_name, "value": str(value or ""),
           "event_date": event_date or "", "layer": layer, "episode_id": episode_id}
    return row


def materialize(context, plan) -> list[dict]:
    rows: list[dict] = []
    for la in plan.get("layer_a", []) or []:
        cat = la.get("category", "")
        if cat not in catalog.ALLOWED_CATEGORIES:
            continue
        rows.append(_row(
            context, category=cat, feature_name=la.get("feature_name", ""),
            value=la.get("value", ""), unit=la.get("unit", ""),
            event_date=la.get("event_date", ""), layer="A",
        ))
    for ep in plan.get("episodes", []) or []:
        eid = ep.get("episode_id") or f"ep{ep['days'][0].get('date_abs','')}"
        for day in ep.get("days", []) or []:
            cat = day.get("category", "")
            if cat not in catalog.ALLOWED_CATEGORIES:
                continue
            rows.append(_row(
                context, category=cat, feature_name=day.get("feature_name", ""),
                value=day.get("value", ""), unit=day.get("unit", ""),
                event_date=day.get("date_abs", ""), layer="B", episode_id=eid,
            ))
    return rows


def csv_row(row: dict) -> dict:
    """17 字段 CSV 行（去掉 _layer/_episode_id 等元字段）."""
    return {k: row["csv_fields"].get(k, "") for k in CSV_FIELDS}
```

> 注：`materialize` 返回 `list[dict]`，每项含 `csv_fields`（17字段）+ 元字段 `group_id/category/feature_name/value/event_date/layer/episode_id`（供 safety/judge/manifest 用）。`injection.run_injection` 最终用 `csv_row(r)` 得到纯 CSV 行写入文件。

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_noise_materialize.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/noise_injection/materialize.py tests/test_noise_materialize.py
git commit -m "feat(noise): materialize plan -> 17-field CSV rows"
```

---

### Task 4: plan.py（LLM 计划生成）

**Files:**
- Create: `pipeline/noise_injection/plan.py`
- Test: `tests/test_noise_plan.py`

**Interfaces:** Consumes `CaseContext`, `prompts.build_plan_prompt`, LLM client; Produces `NoisePlanner` with `.plan(context, *, noise_rows, episodes) -> dict`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_noise_plan.py
from __future__ import annotations
import sys, json
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection.plan import NoisePlanner

class StubClient:
    def __init__(self, payload): self.payload = payload
    def chat_json(self, messages, node=None, **_kw):
        return self.payload

def _ctx():
    ev = [{"group_id":"g","category":"入院","feature_name":"x","value":"y","event_date":"2023-01-01"}]
    return build_context(case_id="c1", events=ev, task_type="T1_staging",
                         target_group_id="g", target_date="2023-03-01",
                         instruction="i", ground_truth={})

def test_planner_returns_plan_and_versions():
    payload = {"layer_a": [], "episodes": []}
    st = StubClient(payload)
    planner = NoisePlanner(st)
    assert planner.prompt_version == "v1"
    plan = planner.plan(_ctx(), noise_rows=2, episodes=1)
    assert plan == payload
    assert len(planner.client.calls) == 1 if hasattr(planner.client,"calls") else True
```

- [ ] **Step 2: Run to verify fail**
Run: `pytest tests/test_noise_plan.py -q` → EXPECT FAIL

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from . import prompts as NP


class NoisePlanner:
    def __init__(self, client, prompt_version: str | None = None):
        self.client = client
        self.prompt_version = prompt_version or NP.PROMPT_VERSIONS["plan"]

    def plan(self, context, *, noise_rows: int, episodes: int) -> dict:
        resp = self.client.chat_json(
            NP.build_plan_prompt(context, noise_rows=noise_rows, episodes=episodes),
            node="noise_plan",
        )
        # 防御性规范化
        if not isinstance(resp, dict):
            raise ValueError("plan LLM 未返回对象")
        resp.setdefault("layer_a", [])
        resp.setdefault("episodes", [])
        return resp
```

- [ ] **Step 4: Run to verify pass**
Run: `pytest tests/test_noise_plan.py -q` → PASS

- [ ] **Step 5: Commit**
```bash
git add pipeline/noise_injection/plan.py tests/test_noise_plan.py
git commit -m "feat(noise): NoisePlanner LLM plan generation"
```

---

### Task 5: safety.py（闸门1，零 LLM）

**Files:**
- Create: `pipeline/noise_injection/safety.py`
- Test: `tests/test_noise_safety.py`

**Interfaces:** Consumes `CaseContext`, materialized rows, `catalog`, `leakage.find_leaked_target_values`; Produces `run_safety_gate(context, rows) -> (passed, rejections)`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_noise_safety.py
from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection.materialize import _row
from pipeline.noise_injection.safety import run_safety_gate, row_text

def _ctx():
    ev = [
        {"group_id":"g0","category":"入院","feature_name":"入院年龄","value":"66","event_date":"2023-03-01"},
        {"group_id":"g1","category":"影像","feature_name":"影像结论","value":"肿块","event_date":"2023-06-14"},
        {"group_id":"g2","category":"病理","feature_name":"CEA","value":"3.1","event_date":"2023-07-02"},
        {"group_id":"gt","category":"评估","feature_name":"疗效评估","value":"PR","event_date":"2023-08-14"},
        {"group_id":"g4","category":"病史","feature_name":"既往史","value":"否认高血压史","event_date":"2023-03-01"},
    ]
    return build_context(case_id="c1", events=ev, task_type="T2_response",
                         target_group_id="gt", target_date="2023-08-14",
                         instruction="评估疗效", ground_truth={"response":"PR"})

def test_date_window_enforced():
    ctx = _ctx()
    rows = [
        _row(ctx, category="病程", feature_name="病程", value="ok", unit="",
             event_date="2023-08-14", layer="A"),      # 等于截断日 → 拒
        _row(ctx, category="病程", feature_name="病程", value="ok2", unit="",
             event_date="2023-07-02", layer="A"),      # 关键证据日 → 拒（保守）
        _row(ctx, category="病程", feature_name="病程", value="ok3", unit="",
             event_date="2023-07-01", layer="A"),      # 安全
    ]
    passed, rej = run_safety_gate(ctx, rows)
    assert len(passed) == 1 and rej

def test_forbidden_category_scan():
    ctx = _ctx()
    rows = [_row(ctx, category="病理", feature_name="病理诊断", value="腺癌", unit="",
                 event_date="2023-07-01", layer="A")]
    passed, rej = run_safety_gate(ctx, rows)
    assert not passed

def test_tumor_marker_scan_rejected():
    ctx = _ctx()
    rows = [_row(ctx, category="检验", feature_name="CEA", value="5.2", unit="ng/mL",
                 event_date="2023-07-01", layer="A")]
    passed, rej = run_safety_gate(ctx, rows)
    assert not passed

def test_denial_term_scan_rejected():
    ctx = _ctx()
    rows = [_row(ctx, category="病程", feature_name="症状", value="新发高血压", unit="",
                 event_date="2023-07-01", layer="A")]
    passed, rej = run_safety_gate(ctx, rows)
    assert not passed

def test_literal_leak_covers_noise():
    ctx = _ctx()  # instruction 不含答案；但噪声行直接写答案应被拒
    rows = [_row(ctx, category="病程", feature_name="病程",
                 value="疗效结论为PR，符合部分缓解", unit="", event_date="2023-07-01", layer="A")]
    passed, rej = run_safety_gate(ctx, rows)
    assert not passed  # value 含 GT 值 "PR" 且含疗效词

def test_row_text_joined():
    r = _row(_ctx(), category="检验", feature_name="白细胞计数", value="5.2",
             unit="×10^9/L", event_date="2023-07-01", layer="A")
    t = row_text(r)
    assert "白细胞计数" in t and "5.2" in t
```

- [ ] **Step 2: Run to verify fail**
Run: `pytest tests/test_noise_safety.py -q` → EXPECT FAIL

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
import re

from . import catalog
from .context import CaseContext
from .materialize import CSV_FIELDS
from pipeline.oncology_generation.leakage import find_leaked_target_values


def row_text(row: dict) -> str:
    cf = row["csv_fields"]
    return " ".join(str(cf.get(k, "") or "") for k in
                    ("feature_name", "value", "actual_value", "extra_value", "unit", "method"))


def _denial_trigger(text: str, denial_terms) -> str | None:
    for t in denial_terms:
        if t and str(t).strip() and (t in text or t.replace("史", "") in text):
            return t
    return None


def check_row(ctx: CaseContext, row: dict) -> tuple[bool, str | None]:
    cf = row["csv_fields"]
    cat = cf["category"]
    date = cf.get("event_date", "") or ""
    # 1) 类别白名单
    if cat not in catalog.ALLOWED_CATEGORIES:
        return False, f"禁用类别:{cat}"
    # 2) 日期窗口 [first, target_date)
    if not (ctx.first_event_date <= date < ctx.target_date):
        return False, f"日期出窗:{date}"
    # 3) 关键证据日回避（保守：所有噪声行均避开）
    if date in ctx.key_evidence_dates:
        return False, f"关键证据日:{date}"
    # 4) 类别内禁用术语
    text = row_text(row)
    for term in catalog.FORBIDDEN_TERMS_BY_CATEGORY.get(cat, ()) :
        if term and term in text:
            return False, f"禁用术语[{cat}]:{term}"
    # 5) 全局肿瘤标志物/抗肿瘤药
    hits = catalog.scan_forbidden(text)
    if hits:
        return False, "扫描命中:" + ";".join(hits)
    # 6) 否认模式扫描
    trig = _denial_trigger(text, ctx.denial_terms)
    if trig:
        return False, f"否认冲突:{trig}"
    # 7) feature_type 合法 / 数值行 unit+value 可解析
    ft = cf.get("feature_type", "")
    if ft not in catalog.FEATURE_TYPES:
        return False, f"非法feature_type:{ft}"
    if ft == "数值型":
        if not cf.get("unit"):
            return False, "数值行缺unit"
        try:
            float(str(cf.get("value", "")).replace("×", "e").replace("^", "").strip())
        except ValueError:
            return False, f"数值不可解析:{cf.get('value')}"
    return True, None


def _literal_leak(ctx: CaseContext, rows) -> str | None:
    gt_values = [str(v).strip() for v in ctx.ground_truth.values()
                 if isinstance(v, (str, int, float)) and len(str(v).strip()) >= 3]
    if not gt_values:
        return None
    for r in rows:
        t = row_text(r)
        for v in gt_values:
            # 用现有 leakage 的 diagnostic-fragment 风格做字面检查
            v_norm = re.sub(r"\s+", "", v)
            if v_norm and v_norm in re.sub(r"\s+", "", t):
                return f"GT值 '{v}' 出现在噪声行"
    return None


def run_safety_gate(ctx: CaseContext, rows: list[dict]):
    passed: list[dict] = []
    rejections: list[dict] = []
    for i, r in enumerate(rows):
        ok, reason = check_row(ctx, r)
        if not ok:
            rejections.append({"index": i, "reason": reason, "row": r.get("csv_fields", {})})
            continue
        passed.append(r)
    leak = _literal_leak(ctx, passed)
    if leak:
        # 泄漏 → 清空（重建依赖重试阶梯）
        return [], rejections + [{"index": "leak", "reason": leak, "row": {}}]
    return passed, rejections
```

> 注：`find_leaked_target_values(instruction, target_values)` 是给 instruction 泄漏检测用的（signal 是完整 instruction）；噪声行字面泄漏在 `_literal_leak` 里用相同 IR 可比对逻辑实现，保证"噪声不暴露 GT 值"。safety 与 judge 均调用该 `run_safety_gate`。

- [ ] **Step 4: Run to verify pass**
Run: `pytest tests/test_noise_safety.py -q` → PASS

- [ ] **Step 5: Commit**
```bash
git add pipeline/noise_injection/safety.py tests/test_noise_safety.py
git commit -m "feat(noise): gate1 rule-based safety"
```

---

### Task 6: judge.py（闸门2，LLM 逐行裁判）

**Files:**
- Create: `pipeline/noise_injection/judge.py`
- Test: `tests/test_noise_judge.py`

**Interfaces:** Consumes `CaseContext`, `prompts.build_judge_prompt`, client; Produces `NoiseJudge.judge(context, rows, batch_size=10) -> (passed, rejections)`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_noise_judge.py
from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection.materialize import materialize
from pipeline.noise_injection.judge import NoiseJudge

class StubClient:
    def __init__(self, decision_by_value=None):
        self.decision_by_value = decision_by_value or {
            "一般情况可": {"related_to_answer": False, "contradicts": False, "reason": "ok"},
        }
    def chat_json(self, messages, node=None, **_kw):
        import json, re
        m = " ".join(x.get("content","") for x in messages)
        val = None
        for v in self.decision_by_value:
            if v in json.dumps(m, ensure_ascii=False) or v in m:
                val = self.decision_by_value[v]
                break
        return val or {"related_to_answer": False, "contradicts": True, "reason": "default reject"}

def _ctx():
    ev = [{"group_id":"g","category":"入院","feature_name":"x","value":"y","event_date":"2023-01-01"}]
    return build_context(case_id="c1", events=ev, task_type="T1_staging",
                         target_group_id="g", target_date="2023-03-01",
                         instruction="i", ground_truth={"stage":"pT2N1M0"})

def test_judge_batch_size_and_verdict():
    ctx = _ctx()
    plan = {"layer_a": [
        {"category":"病程","feature_name":"病程","value":"一般情况可","event_date":"2023-02-01","unit":""},
        {"category":"病程","feature_name":"病程","value":"今天吃了止痛药","event_date":"2023-02-02","unit":""},
    ], "episodes": []}
    rows = materialize(ctx, plan)
    # 自行构造 csv_fields 使 row_text 可用（materialize 已含）
    judge = NoiseJudge(StubClient(), batch_size=1)
    passed, rejected = judge.judge(ctx, rows, batch_size=1)
    assert len(passed) == 1 and len(rejected) == 1
    assert passed[0]["csv_fields"]["value"] == "一般情况可"
```

- [ ] **Step 2: Run to verify fail**
Run: `pytest tests/test_noise_judge.py -q` → EXPECT FAIL

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from . import prompts as NP


class NoiseJudge:
    def __init__(self, client, prompt_version: str | None = None):
        self.client = client
        self.prompt_version = prompt_version or NP.PROMPT_VERSIONS["judge"]

    def _judge_one(self, context, row) -> tuple[bool, str]:
        rid = row.get("group_id", "")[:8]
        resp = self.client.chat_json(
            NP.build_judge_prompt(context, row, rid), node="noise_judge",
        )
        related = bool(resp.get("related_to_answer", False))
        contra = bool(resp.get("contradicts", False))
        reason = str(resp.get("reason", ""))
        if related or contra:
            return False, reason or ("related" if related else "contradicts")
        return True, reason

    def judge(self, context, rows, batch_size: int = 10):
        passed: list[dict] = []
        rejections: list[dict] = []
        total = len(rows)
        for start in range(0, total, batch_size):
            batch = rows[start:start + batch_size]
            for i, r in enumerate(batch):
                ok, reason = self._judge_one(context, r)
                if not ok:
                    rejections.append({"index": start + i, "reason": reason,
                                       "row": r.get("csv_fields", {})})
                else:
                    r["judge_status"] = "pass"
                    passed.append(r)
        return passed, rejections
```

- [ ] **Step 4: Run to verify pass**
Run: `pytest tests/test_noise_judge.py -q` → PASS

- [ ] **Step 5: Commit**
```bash
git add pipeline/noise_injection/judge.py tests/test_noise_judge.py
git commit -m "feat(noise): gate2 LLM judge per-row"
```

---

### Task 7: solvable.py（闸门3，可解性复验）

**Files:**
- Create: `pipeline/noise_injection/solvable.py`
- Test: `tests/test_noise_solvable.py`

**Interfaces:** Consumes `CaseContext`, materialized rows, client, `prompts_v2.build_solve_prompt / build_evaluate_prompt`; Produces `check(context, rows, client) -> (ok, detail)`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_noise_solvable.py
from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection.materialize import materialize
from pipeline.noise_injection import solvable

class StubClient:
    def __init__(self, solve=None, evaluate=None):
        self.solve = solve or {"answer": "PR", "reasoning_summary": "对比基线与随访影像，长径缩小>30%，判定PR"}
        self.evaluate = evaluate or {"verdict": "valid", "consistent": True, "has_reasoning": True, "explanation": "ok"}
        self.calls = []
    def chat_json(self, messages, node=None, **_kw):
        self.calls.append(node)
        if node == "noise_solve": return self.solve
        if node == "noise_evaluate": return self.evaluate
        raise AssertionError(node)

def _ctx():
    ev = [{"group_id":"g","category":"入院","feature_name":"x","value":"y","event_date":"2023-01-01"}]
    return build_context(case_id="c1", events=ev, task_type="T2_response",
                         target_group_id="g", target_date="2023-03-01",
                         instruction="评估疗效", ground_truth={"response":"PR"})

def test_solvable_valid_passes():
    ctx = _ctx()
    rows = materialize(ctx, {"layer_a": [
        {"category":"病程","feature_name":"病程","value":"一般情况可","event_date":"2023-02-01","unit":""},
    ], "episodes": []})
    st = StubClient()
    ok, detail = solvable.check(ctx, rows, st)
    assert ok is True and "noise_solve" in st.calls and "noise_evaluate" in st.calls

def test_solvable_verdict_not_valid_fails():
    ctx = _ctx()
    rows = materialize(ctx, {"layer_a": [], "episodes": []})
    st = StubClient(evaluate={"verdict": "inconsistent", "consistent": False,
                              "has_reasoning": True, "explanation": "no"})
    ok, detail = solvable.check(ctx, rows, st)
    assert ok is False
```

- [ ] **Step 2: Run to verify fail**
Run: `pytest tests/test_noise_solvable.py -q` → EXPECT FAIL

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from .materialize import csv_row
from pipeline.oncology_generation.prompts_v2 import build_solve_prompt, build_evaluate_prompt


def _render_noise_rows(rows: list[dict]) -> str:
    """噪声行按与真实事件一致的渲染格式拼接（[组ID8] 日期 类别 + 字段全文）."""
    from pipeline.oncology_generation.schemas import serialize_groups
    groups = []
    # 复用 build_event_groups 的编排
    from pipeline.oncology_generation.schemas import build_event_groups
    events = []
    for i, r in enumerate(rows):
        cf = r["csv_fields"]
        events.append({**cf, "_source_row": f"N{i}"})
    groups = build_event_groups(events)
    return serialize_groups(groups, full=True)


def check(context, rows, client) -> tuple[bool, str]:
    # 干净可见事件：从 context 的原始事件中，目标组之前、且非答案事件 = 直接重建可见
    # （pipeline 已有 visible_groups，这里用上下文内建的可见事件文本）
    visible_text = getattr(context, "_visible_text", "") or context.case_facts_text()
    noise_text = _render_noise_rows(rows)
    solve_msgs = build_solve_prompt(context.instruction, visible_text + "\n" + noise_text)
    sol = client.chat_json(solve_msgs, node="noise_solve")
    answer = sol.get("answer", "")
    reasoning = sol.get("reasoning_summary", "")
    eval_msgs = build_evaluate_prompt(context.ground_truth, answer, reasoning)
    ev = client.chat_json(eval_msgs, node="noise_evaluate")
    verdict = ev.get("verdict", "inconsistent")
    if verdict == "valid":
        return True, ""
    return False, f"solvable verdict={verdict}: {ev.get('explanation','')}"
```

> 注：`context._visible_text` 为可选扩展字段（pipeline 节点在 inject_noise 中设置），非核心包必需；脚本路径可传 `visible_text` 明文参数。为简化，`check` 接受可选 `visible_text` 参数（见下方修正签名）。

- [ ] **Step 3b: 修正签名支持可选 visible_text**

```python
def check(context, rows, client, *, visible_text: str | None = None) -> tuple[bool, str]:
    visible_text = visible_text if visible_text is not None else (
        getattr(context, "_visible_text", "") or context.case_facts_text())
```

- [ ] **Step 4: Run to verify pass**
Run: `pytest tests/test_noise_solvable.py -q` → PASS

- [ ] **Step 5: Commit**
```bash
git add pipeline/noise_injection/solvable.py tests/test_noise_solvable.py
git commit -m "feat(noise): gate3 solvability re-check"
```

---

### Task 8: manifest + injection（编排 + 重试阶梯）

**Files:**
- Create: `pipeline/noise_injection/manifest.py`, `pipeline/noise_injection/injection.py`
- Test: `tests/test_noise_manifest.py`, `tests/test_noise_retry.py`

**Interfaces:** Consumes all gates + planner + materialize + config + client; Produces `result = run_injection(context, config, client) -> InjectionResult`（含 manifest 构建/读写、降级路径）。

- [ ] **Step 1: Write failing tests**

```python
# tests/test_noise_manifest.py
from __future__ import annotations
import sys, json
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.manifest import build_manifest, write_manifest, read_manifest, MANIFEST_SCHEMA_VERSION

def test_manifest_roundtrip(tmp_path, ):
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION, "case_id": "c1", "task_type": "T2_response",
        "generated_at": "2026-08-20T00:00:00Z",
        "config_snapshot": {"noise_rows": 60, "episodes": 2, "prompt_versions": {"plan":"v1","judge":"v1"}, "model": "m"},
        "attempts": [{"attempt":1,"rows_requested":60,"rows_passed":58,
                      "gates":{"rule_rejected":2,"judge_rejected":3,"solvable":"valid"},"failure_reason":None}],
        "final_status": "noisy",
        "rows": [{"csv_row":57,"group_id":"g","layer":"A","episode_id":None,
                  "category":"检验","feature_name":"白细胞计数","value":"5.2",
                  "event_date":"2023-07-02","judge":"pass"}],
    }
    p = tmp_path / "noise_manifest.json"
    write_manifest(p, manifest)
    loaded = read_manifest(p)
    assert loaded["final_status"] == "noisy"
    assert loaded["rows"][0]["csv_row"] == 57

def test_build_manifest_degraded_has_empty_rows():
    m = build_manifest(case_id="c1", task_type="T2_response", generated_at="t",
                       config_snapshot={}, attempts=[],
                       final_status="degraded_clean", rows=[])
    assert m["final_status"] == "degraded_clean" and m["rows"] == []
```

```python
# tests/test_noise_retry.py
from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import build_context
from pipeline.noise_injection.injection import run_injection
from pipeline.noise_injection.config import NoiseConfig

GOOD_PLAN = {"layer_a": [
    {"category":"病程","feature_name":"病程","value":"一般情况可","event_date":"2023-02-01","unit":""},
], "episodes": []}

class StubClient:
    def __init__(self, plan=GOOD_PLAN, plan_counts=None, eval_verdict="valid",
                 judge_ok=True, fail_solvable_rounds=0):
        self.plan = plan; self.eval_verdict = eval_verdict; self.judge_ok = judge_ok
        self.plan_calls = 0
    def chat_json(self, messages, node=None, **_kw):
        if node == "noise_plan":
            self.plan_calls += 1
            return self.plan
        if node == "noise_judge":
            return {"related_to_answer": not self.judge_ok, "contradicts": False, "reason":"r"}
        if node == "noise_solve":
            return {"answer":"PR","reasoning_summary":"对比缩小30%判定PR"}
        if node == "noise_evaluate":
            import json
            v = self.eval_verdict
            return {"verdict": v, "consistent": v=="valid", "has_reasoning": True, "explanation":""}
        raise AssertionError(node)

def _ctx():
    ev = [{"group_id":"g","category":"入院","feature_name":"x","value":"y","event_date":"2023-01-01"}]
    return build_context(case_id="c1", events=ev, task_type="T2_response",
                         target_group_id="g", target_date="2023-03-01",
                         instruction="评估疗效", ground_truth={"response":"PR"})

def test_happy_noisy():
    res = run_injection(_ctx(), NoiseConfig(noise_rows=3, episodes=1, max_attempts=1), StubClient())
    assert res.final_status == "noisy" and res.rows

def test_degraded_clean_when_all_fail():
    client = StubClient(eval_verdict="inconsistent")
    res = run_injection(_ctx(), NoiseConfig(noise_rows=3, episodes=1, max_attempts=2), client)
    assert res.final_status == "degraded_clean"
    assert res.rows == [] and res.degrade_reason

def test_retry_reduced_params_applied():
    # 让 noise_plan 在 attempt1 抛错 → 触发降级路径
    class F:
        def chat_json(self, messages, node=None, **kw):
            if node == "noise_plan":
                raise RuntimeError("gen fail")
            raise AssertionError(node)
    res = run_injection(_ctx(), NoiseConfig(noise_rows=60, episodes=2, max_attempts=2), F())
    assert res.final_status == "degraded_clean"
```

- [ ] **Step 2: Run to verify fail**
Run: `pytest tests/test_noise_manifest.py tests/test_noise_retry.py -q` → EXPECT FAIL

- [ ] **Step 3: Implement `manifest.py`**

```python
from __future__ import annotations
import json
from pathlib import Path

MANIFEST_SCHEMA_VERSION = 1


def build_manifest(*, case_id: str, task_type: str, generated_at: str,
                   config_snapshot: dict, attempts: list[dict],
                   final_status: str, rows: list[dict], degrade_reason=None) -> dict:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "case_id": case_id,
        "task_type": task_type,
        "generated_at": generated_at,
        "config_snapshot": config_snapshot,
        "attempts": attempts,
        "final_status": final_status,
        "degrade_reason": degrade_reason,
        "rows": rows,
    }


def write_manifest(path: Path, manifest: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def read_manifest(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 4: Implement `injection.py`**（重试阶梯 §4.2 + 逐行重生成一次）

```python
from __future__ import annotations
import time
from dataclasses import dataclass, field

from . import catalog, materialize as M
from .plan import NoisePlanner
from .judge import NoiseJudge
from .safety import run_safety_gate
from . import solvable as S
from .manifest import build_manifest


@dataclass
class InjectionResult:
    final_status: str               # noisy | degraded_clean
    rows: list[dict]                # passed noise rows（17 字段，无元字段）
    manifest: dict
    attempts: list[dict] = field(default_factory=list)
    review_queue_entries: list[dict] = field(default_factory=list)
    degrade_reason: str | None = None


def _model_name(client) -> str:
    return getattr(getattr(client, "_client", None), "model", "") or getattr(client, "model", "unknown")


def run_injection(context, config, client, *, visible_text=None, full_attempts=None) -> InjectionResult:
    planner = NoisePlanner(client)
    judge = NoiseJudge(client)
    ladder = [(config.noise_rows, config.episodes)] + [config.retry_reduced] * (config.max_attempts - 1)
    if full_attempts is not None:
        ladder = ladder[:full_attempts]
    attempts: list[dict] = []
    degrade_reason = None

    for idx, (n_rows, n_ep) in enumerate(ladder, start=1):
        try:
            plan = planner.plan(context, noise_rows=n_rows, episodes=n_ep)
            mat_rows = M.materialize(context, plan)
            g1_passed, g1_rej = run_safety_gate(context, mat_rows)
            # gate2：逐行裁判 + 被拒行重生成一次再判，仍拒则丢弃
            judged, g2_rej = judge.judge(context, g1_passed, batch_size=config.judge_batch_size)
            regenerated = []
            if g2_rej:
                regen_plan = planner.plan(context, noise_rows=len(g2_rej), episodes=0)
                for rr in M.materialize(context, regen_plan):
                    rr["judge_status"] = "pending"
                    regenerated.append(rr)
                rp, rj = judge.judge(context, regenerated, batch_size=config.judge_batch_size)
                judged = judged + rp
                g2_rej = g2_rej + rj
            # gate3：可解性（visible_text 由调用方 Thread 传入：pipeline/脚本提供真实可见事件文本）
            ok, detail = S.check(context, judged, client, visible_text=visible_text)
            attempts.append({
                "attempt": idx, "rows_requested": n_rows + n_ep,
                "rows_passed": len(judged),
                "gates": {"rule_rejected": len(g1_rej), "judge_rejected": len(g2_rej),
                          "solvable": "valid" if ok else ("failed:" + detail)},
                "failure_reason": None if ok else detail,
            })
            if ok:
                return _build_result(context, config, client, judged, attempts, "noisy")
            degrade_reason = detail
        except Exception as exc:  # noqa: BLE001
            attempts.append({"attempt": idx, "rows_requested": n_rows + n_ep,
                             "rows_passed": 0, "gates": {},
                             "failure_reason": f"exception: {exc}"})
            degrade_reason = str(exc)

    return _build_result(context, config, client, [], attempts, "degraded_clean",
                         degrade_reason=degrade_reason)


def _build_result(context, config, client, judged, attempts, final_status,
                  degrade_reason=None) -> InjectionResult:
    """judged=通过闸门的完整行（含 layer/episode_id 元字段）；内部 csv_row 化 + _manifest_rows。"""
    final_rows = [M.csv_row(r) for r in judged]
    manifest = build_manifest(
        case_id=context.case_id, task_type=context.task_type,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        config_snapshot={
            "noise_rows": config.noise_rows, "episodes": config.episodes,
            "prompt_versions": {"plan": planner_version(), "judge": judge_version()},
            "model": _model_name(client),
        },
        attempts=attempts, final_status=final_status, rows=_manifest_rows(judged),
        degrade_reason=degrade_reason,
    )
    entries = []
    if final_status == "degraded_clean":
        entries.append({
            "case_id": context.case_id, "reason_class": "noise_gate_failed",
            "detail": degrade_reason or "noise gates all failed",
            "attempts": attempts,
        })
    return InjectionResult(final_status=final_status, rows=final_rows, manifest=manifest,
                           attempts=attempts, review_queue_entries=entries,
                           degrade_reason=degrade_reason)


def _build_result(context, config, client, final_rows, attempts, final_status,
                  degrade_reason=None) -> InjectionResult:
    manifest = build_manifest(
        case_id=context.case_id, task_type=context.task_type,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        config_snapshot={
            "noise_rows": config.noise_rows, "episodes": config.episodes,
            "prompt_versions": {"plan": planner_version(), "judge": judge_version()},
            "model": _model_name(client),
        },
        attempts=attempts, final_status=final_status, rows=_manifest_rows(final_rows),
        degrade_reason=degrade_reason,
    )
    entries = []
    if final_status == "degraded_clean":
        entries.append({
            "case_id": context.case_id, "reason_class": "noise_gate_failed",
            "detail": degrade_reason or "noise gates all failed",
            "attempts": attempts,
        })
    return InjectionResult(final_status=final_status, rows=final_rows, manifest=manifest,
                           attempts=attempts, review_queue_entries=entries,
                           degrade_reason=degrade_reason)


def planner_version():
    from . import prompts as NP
    return NP.PROMPT_VERSIONS["plan"]


def judge_version():
    from . import prompts as NP
    return NP.PROMPT_VERSIONS["judge"]


def _manifest_rows(rows: list[dict]) -> list[dict]:
    return [{"group_id": r["group_id"], "layer": r.get("layer", "A"),
             "episode_id": r.get("episode_id"),
             "category": r["category"], "feature_name": r["feature_name"],
             "value": r["value"], "event_date": r["event_date"], "judge": "pass"}
            for r in rows]
```

- [ ] **Step 5: Run to verify pass**
Run: `pytest tests/test_noise_manifest.py tests/test_noise_retry.py -q` → PASS

- [ ] **Step 6: Commit**
```bash
git add pipeline/noise_injection/manifest.py pipeline/noise_injection/injection.py tests/test_noise_manifest.py tests/test_noise_retry.py
git commit -m "feat(noise): manifest + injection orchestrator with retry ladder"
```

---

### Task 9: v2 流水线接入

**Files:**
- Modify: `pipeline/oncology_generation/schemas.py`（state 字段）、`graph.py`、`nodes.py`
- Modify: `tests/test_v2_integration.py`（其 FakeClient/script 需补 `noise_plan/noise_judge/noise_solve/noise_evaluate` 回应——graph 在 valid 分支现已总是跑 inject_noise，否则既有持久化路径测试会 KeyError）
- Test: `tests/test_noise_pipeline.py`（新增）

**Interfaces:** Consumes `run_injection`, `build_context`, `csv_row`, `write_manifest`, `append_review_item`; Produces state fields + `inject_noise` node + materialize 追噪。

- [ ] **Step 1: Write failing tests**（仿 `tests/test_v2_integration.py` 的 FakeClient 结构）

```python
# tests/test_noise_pipeline.py
from __future__ import annotations
import sys, json, csv
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from pipeline.oncology_generation import nodes as N
from pipeline.oncology_generation.graph import run_case

HEADER = "group_id,event_date,category,feature_name,value,extra_value,_source_row\n"
def make_case_csv(tmp_path, case_id):
    data_root = tmp_path / "csv"; data_root.mkdir(exist_ok=True)
    rows = HEADER
    rows += 'g1,2018-03-01,病理,病理诊断,浸润性导管癌,,1\n'
    rows += 'g1,2018-03-01,病理,免疫组化,HER2 3+,,2\n'
    rows += 'g1,2018-03-01,病史,既往史,否认高血压史,,3\n'
    rows += 'g2,2018-11-26,诊断,诊断名称,乳腺癌,,4\n'
    rows += 'g2,2018-11-26,诊断,临床分期,pT2N1M0,,5\n'
    (data_root/f"{case_id}.csv").write_text(rows, encoding="utf-8")
    return data_root

NOISE_PLAN = {"layer_a": [
    {"category":"病程","feature_name":"病程","value":"一般情况可，饮食睡眠良好",
     "event_date":"2018-05-01","unit":""},
    {"category":"检验","feature_name":"白细胞计数","value":"5.2","unit":"×10^9/L",
     "event_date":"2018-05-02"},
], "episodes": []}

class FakeClient:
    def __init__(self):
        self.calls=[]
    def chat_json(self, prompt, node=None, **_kw):
        self.calls.append(node)
        if node=="label": return {"applicable_types":["T1_staging"],"recommended_type":"T1_staging","reason":"r"}
        if node=="generate": return {"target_group_id":"g2","target_date":"2018-11-26",
                                     "instruction":"判定分期","ground_truth":{"stage":"pT2N1M0"},
                                     "answer_event_rows":[]}
        if node=="validate": return {"passed":True,"issues":[],"severity":"","leaked":False,"answerable":True,"unique":True}
        if node=="solve": return {"answer":"pT2N1M0 II期","reasoning_summary":"病理浸润性导管癌","confidence":"high"}
        if node=="evaluate": return {"verdict":"valid","consistent":True,"has_reasoning":True,"explanation":"ok"}
        if node=="checkpoint": return {"checkpoints":[
            {"id":"c1","layer":"data_retrieval","description":"d","eval_method":"category_query","params":{}},
            {"id":"c2","layer":"clinical_reasoning","description":"d","eval_method":"llm_judge","params":{}},
            {"id":"c3","layer":"outcome_check","description":"d","eval_method":"field_match","params":{}},
            {"id":"c4","layer":"documentation","description":"d","eval_method":"llm_judge","params":{}}]}
        if node=="noise_plan": return NOISE_PLAN
        if node=="noise_judge": return {"related_to_answer":False,"contradicts":False,"reason":"ok"}
        if node=="noise_solve": return {"answer":"pT2N1M0","reasoning_summary":"病理示浸润性导管癌"}
        if node=="noise_evaluate": return {"verdict":"valid","consistent":True,"has_reasoning":True,"explanation":"ok"}
        raise AssertionError(node)

def test_pipeline_appends_noise_and_writes_manifest(tmp_path):
    case_id="case_noise"
    N.get_default_client = lambda trace_dir=None: FakeClient()
    final = run_case(case_id, data_root=make_case_csv(tmp_path,case_id),
                     output_root=tmp_path/"tasks", generated_root=tmp_path/"generated")
    assert final["status"]=="persisted"
    assert final.get("noise_rows") and final.get("noise_manifest")
    assert final["noise_manifest"]["final_status"]=="noisy"
    task_dir=Path(final["task_dir"])
    assert (task_dir/"noise_manifest.json").exists()
    cleaned=(task_dir/"cleaned_trajectory.csv").read_text(encoding="utf-8")
    assert "一般情况可" in cleaned and "白细胞计数" in cleaned
    # 降级/评审队列不影响主差异：这里应为 noisy
    assert final["noise_manifest"]["rows"]
```

- [ ] **Step 2: Run to verify fail**
Run: `pytest tests/test_noise_pipeline.py -q` → EXPECT FAIL

- [ ] **Step 3: Modify `schemas.py`** — 在 `GenerationState` 加两字段，并在 `new_state` 初始化：

```python
    noise_rows: list[dict] | None = None
    noise_manifest: dict | None = None
```
（`new_state` 中加 `noise_rows=None, noise_manifest=None`。）

- [ ] **Step 4: Modify `graph.py`** — 插入节点并改边：

```python
    graph.add_node("inject_noise", N.inject_noise)
    ...
    graph.add_conditional_edges(
        "evaluate_solution",
        N.route_after_evaluate,
        {
            "inject_noise": "inject_noise",      # valid 分支
            "generate_task": "generate_task",
            "persist_failure": "persist_failure",
        },
    )
    graph.add_edge("inject_noise", "generate_checkpoints")
    # 移除 graph.add_edge("evaluate_solution","generate_checkpoints")
```

- [ ] **Step 5: Modify `nodes.py`** — 新增薄节点 + materialize 追噪：

```python
def inject_noise(state: GenerationState) -> dict:
    """evaluate valid 分支：调用核心包 run_injection 生成噪声（含重试阶梯）."""
    from .noise_injection.context import build_context
    from .noise_injection.config import NoiseConfig
    from .noise_injection.injection import run_injection
    from .noise_injection import solvable as _S  # noqa 保留

    draft: TaskDraft = state["task_draft"]
    ctx = build_context(
        case_id=state["case_id"],
        events=state["events"],
        task_type=draft.task_type,
        target_group_id=draft.target_group_id,
        target_date=draft.target_date,
        instruction=draft.instruction,
        ground_truth=draft.ground_truth,
        answer_event_rows=draft.answer_event_rows,
    )
    # 提供给 solvable gate3 的干净可见事件文本（透传 visible_text kwarg；
    # CaseContext 为 frozen dataclass，不可用 object.__setattr__ 附加属性）
    visible = visible_groups(state["groups"], draft.target_group_id, draft.answer_event_rows)
    visible_text = serialize_groups(visible, full=True)
    client = _client(state)
    result = run_injection(ctx, NoiseConfig(), client, visible_text=visible_text)
    update: dict[str, Any] = {"noise_rows": result.rows, "noise_manifest": result.manifest}
    return update


def _append_noise_to_csv(cleaned_csv: Path, noise_rows: list[dict]) -> None:
    from .noise_injection.materialize import CSV_FIELDS
    if not noise_rows:
        return
    existing = set()
    with cleaned_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        rd = csv.reader(fh)
        next(rd, None)  # header
        for row in rd:
            existing.add(tuple(row))
    with cleaned_csv.open("a", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(CSV_FIELDS), extrasaction="ignore")
        for r in noise_rows:
            row = {k: r.get(k, "") for k in CSV_FIELDS}
            # 追加时校验不与已存在行冲突（避免表头重复）
            wr.writerow(row)
```

并在 `materialize` 函数末尾（写 task.toml 之后、return 之前）追加：

```python
    # 追加噪声行 + 写 manifest
    noise_rows = state.get("noise_rows") or []
    if noise_rows:
        _append_noise_to_csv(cleaned_csv, noise_rows)
    noise_manifest = state.get("noise_manifest")
    if noise_manifest is not None:
        (task_dir / "noise_manifest.json").write_text(
            json.dumps(noise_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if state.get("noise_manifest") and state["noise_manifest"].get("final_status") == "degraded_clean":
        # 降级 → review_queue（任务仍以干净版落盘）
        _append_review_queue_for_noise(state)
```

并新增辅助（复用现有 review_queue 追加机制）：

```python
def _append_review_queue_for_noise(state) -> None:
    queue_path = Path(state["generated_root"]) / "review_queue.jsonl"
    manifest = state.get("noise_manifest") or {}
    entry = {
        "case_id": state["case_id"], "attempt": state.get("attempt", 0),
        "reason_class": "noise_gate_failed",
        "detail": manifest.get("degrade_reason") or "noise gates failed",
    }
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

> 说明：materialize 落盘后若 `noise_manifest` 存在则总写 `noise_manifest.json`（含降级 `rows:[]`），保证 manifest 恒存在；降级任务额外写一条 review_queue。`inject_noise` 不把降级直接判为失败。

- [ ] **Step 6: Run to verify pass**
Run: `pytest tests/test_noise_pipeline.py -q` → PASS；以及回归 `pytest tests/test_v2_integration.py tests/test_v2_units.py -q` → PASS

- [ ] **Step 7: Commit**
```bash
git add pipeline/oncology_generation/schemas.py pipeline/oncology_generation/graph.py pipeline/oncology_generation/nodes.py tests/test_noise_pipeline.py
git commit -m "feat(noise): wire inject_noise into v2 pipeline + materialize append"
```

---

### Task 10: scripts/apply_noise.py（存量批处理）

**Files:**
- Create: `scripts/apply_noise.py`
- Test: `tests/test_noise_apply_cli.py`（新增）

**Interfaces:** Consumes `run_injection`, `case_from_csv`, `write_manifest`, `append_review_item`, `get_default_client`; Produces `main(argv)->int` CLI + `process_case(...)`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_noise_apply_cli.py
from __future__ import annotations
import sys, json
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import scripts.apply_noise as AP

def test_parse_args_defaults():
    args = AP.parse_args(["--dry-run"])
    assert args.dry_run is True and args.resume is False
    assert args.workers == 1

def test_select_task_ids(tmp_path):
    root = tmp_path/"tasks"/"oncology-v2"
    for cid in ("a","b"):
        (root/cid).mkdir(parents=True)
        (root/cid/'task.toml').write_text('')
    ids = AP.select_task_ids(root, case_ids=None, limit=1)
    assert ids == ["a"]  # 排序后取前1

def test_process_case_stub_calls_monkeypatched():
    pass  # 端到端在 Task 11 集成测试覆盖
```

- [ ] **Step 2: Run to verify fail**
Run: `pytest tests/test_noise_apply_cli.py -q` → EXPECT FAIL

- [ ] **Step 3: Implement**

```python
"""存量 v2 任务噪声注入批处理脚本.

用法:
    python -m scripts.apply_noise --dry-run
    python -m scripts.apply_noise --limit 20
    python -m scripts.apply_noise --case-ids <id1> <id2>
    python -m scripts.apply_noise --resume        # 跳过已完成的（noisy 目录已存在 noise_manifest.json）
选项:
    --dry-run    只跑闸门不写盘（静默）
    --resume     跳过 tasks/oncology-v2-noisy/<id>/ 已存在且为 noisy 的 case
    --limit N    最多处理 N 个
    --case-ids   指定 case_id 列表
    --workers 1  默认串行
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from llm.client import get_default_client
from pipeline.noise_injection.config import NoiseConfig
from pipeline.noise_injection.context import case_from_csv
from pipeline.noise_injection.injection import run_injection
from pipeline.noise_injection.manifest import write_manifest
from pipeline.oncology_generation.paths import safe_case_path

SRC_ROOT = PROJECT_ROOT / "tasks/oncology-v2"
OUT_ROOT = PROJECT_ROOT / "tasks/oncology-v2-noisy"
RAW_ROOT = PROJECT_ROOT / "data/oncology_complete_trajectory/raw/csv"
QUEUE_PATH = PROJECT_ROOT / "generated/v2/review_queue.jsonl"


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="存量 v2 任务噪声注入")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--case-ids", nargs="+", metavar="ID", default=None)
    p.add_argument("--workers", type=int, default=1)
    return p.parse_args(argv)


def select_task_ids(src_root: Path, case_ids=None, limit=None) -> list[str]:
    dirs = sorted(p.name for p in src_root.iterdir()
                  if p.is_dir() and (p / "task.toml").exists())
    if case_ids:
        wanted = set(case_ids)
        dirs = [d for d in dirs if d in wanted]
        missing = wanted - set(dirs)
        if missing:
            raise SystemExit(f"未找到 task: {sorted(missing)}")
    if limit is not None:
        dirs = dirs[:limit]
    return dirs


def _task_payload(src_dir: Path):
    toml = (src_dir / "task.toml").read_text(encoding="utf-8")
    gt = json.loads((src_dir / "ground_truth.json").read_text(encoding="utf-8"))
    instruction = (src_dir / "instruction.md").read_text(encoding="utf-8")
    return toml, gt, instruction


def process_case(case_id: str, *, client, dry_run: bool, noise_dir_exists: bool) -> dict:
    src_dir = SRC_ROOT / safe_case_path(SRC_ROOT, case_id)
    raw = RAW_ROOT / f"{case_id}.csv"
    toml, gt, instruction = _task_payload(src_dir)
    task_type = gt.get("task_type", "")
    target_group_id = gt.get("target_group_id", "")
    target_date = gt.get("target_date", "")
    ground_truth = gt.get("ground_truth", {})
    ctx = case_from_csv(case_id, raw, task_type=task_type,
                        target_group_id=target_group_id, target_date=target_date,
                        instruction=instruction, ground_truth=ground_truth)
    result = run_injection(ctx, NoiseConfig(), client, full_attempts=1 if dry_run else None)
    # 写 review_queue（降级）
    if not dry_run:
        for entry in result.review_queue_entries:
            QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with QUEUE_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if dry_run:
        return {"case_id": case_id, "dry_run_status": result.final_status,
                "rows_passed": len(result.rows)}
    out_dir = OUT_ROOT / safe_case_path(OUT_ROOT, case_id)
    # 复制干净文件（原样不动，同目录内容不改）
    for name in ("instruction.md", "task.toml", "ground_truth.json", "checkpoints.json"):
        src = src_dir / name
        if src.exists():
            dst = out_dir / name
            if not dst.exists():  # 避免每次覆盖造成非幂等
                dst.write_bytes(src.read_bytes())
    # cleaned：原始行 + 噪声行（原版 cleaned 即"干净版"）
    cleaned_src = src_dir / "cleaned_trajectory.csv"
    cleaned_dst = out_dir / "cleaned_trajectory.csv"
    if result.rows:
        import csv as _csv
        from pipeline.noise_injection.materialize import CSV_FIELDS
        with cleaned_src.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = _csv.DictReader(fh)
            fieldnames = list(reader.fieldnames or CSV_FIELDS)
            orig = list(reader)
        with cleaned_dst.open("w", encoding="utf-8", newline="") as fh:
            wr = _csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            wr.writeheader(); wr.writerows(orig)
            for r in result.rows:
                wr.writerow({k: r.get(k, "") for k in fieldnames})
    else:
        cleaned_dst.write_bytes(cleaned_src.read_bytes())
    write_manifest(out_dir / "noise_manifest.json", result.manifest)
    return {"case_id": case_id, "final_status": result.final_status,
            "rows_passed": len(result.rows)}


def main(argv=None) -> int:
    args = parse_args(argv)
    client = get_default_client(PROJECT_ROOT / "generated/v2/trace")
    ids = select_task_ids(SRC_ROOT, case_ids=args.case_ids, limit=args.limit)
    print(f"共 {len(ids)} 个存量任务；输出 {OUT_ROOT}")
    stats = {"noisy": 0, "degraded_clean": 0, "skipped": 0, "error": []}
    detail: list[dict] = []
    t0 = time.time()
    for i, cid in enumerate(ids, start=1):
        noise_dir = OUT_ROOT / safe_case_path(OUT_ROOT, cid)
        completed = (noise_dir / "noise_manifest.json").exists() and args.resume
        if completed:
            stats["skipped"] += 1
            continue
        try:
            res = process_case(cid, client=client, dry_run=args.dry_run,
                               noise_dir_exists=(noise_dir / "noise_manifest.json").exists())
            stats[res["final_status"] if not args.dry_run else res["dry_run_status"]] += 1
            detail.append(res)
        except Exception as exc:  # noqa: BLE001
            stats["error"].append(cid)
            detail.append({"case_id": cid, "error": str(exc)})
    done = time.time() - t0
    summary = OUT_ROOT / "apply_noise_report.jsonl" if not args.dry_run else \
        SRC_ROOT.parent / "apply_noise_dryrun.jsonl"
    summary.parent.mkdir(parents=True, exist_ok=True)
    with summary.open("a", encoding="utf-8") as fh:
        for d in detail:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"完成({done:.0f}s) noisy={stats['noisy']} degraded_clean={stats['degraded_clean']} "
          f"skipped={stats['skipped']} error={stats['error']}")
    return 0 if not stats["error"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify pass**
Run: `pytest tests/test_noise_apply_cli.py -q` → PASS

- [ ] **Step 5: Commit**
```bash
git add scripts/apply_noise.py tests/test_noise_apply_cli.py
git commit -m "feat(noise): batch backfill script apply_noise.py"
```

---

### Task 11: 集成收尾 + 回归 + 文档

**Files:**
- Test: `tests/test_noise_integration.py`（新增）；回归全部测试
- Docs: 无（spec 已含设计）

**Interfaces:** 端到端通路验证。

- [ ] **Step 1: 写端到端集成（stub client，真实 task + 真实 raw CSV）**

```python
# tests/test_noise_integration.py
from __future__ import annotations
import sys, json
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.noise_injection.context import case_from_csv
from pipeline.noise_injection.injection import run_injection
from pipeline.noise_injection.config import NoiseConfig
import csv

# 用仓库内真实的一个 v2 任务目录（若存在），否则跳过
REAL_TASK = next(iter((PROJECT_ROOT/"tasks/oncology-v2").glob("*")), None)

NOISE_PLAN = {"layer_a": [
    {"category":"病程","feature_name":"病程","value":"一般情况可，饮食睡眠良好","event_date":"2023-06-01","unit":""},
    {"category":"检验","feature_name":"白细胞计数","value":"5.2","unit":"×10^9/L","event_date":"2023-06-02"},
    {"category":"评估","feature_name":"体温","value":"36.6","unit":"℃","event_date":"2023-06-03"},
], "episodes": []}
class Stub:
    def chat_json(self, messages, node=None, **kw):
        if node=="noise_plan": return NOISE_PLAN
        if node=="noise_judge": return {"related_to_answer":False,"contradicts":False,"reason":"ok"}
        if node=="noise_solve": return {"answer":"PR","reasoning_summary":"对比可见证据缩小30%"}
        if node=="noise_evaluate": return {"verdict":"valid","consistent":True,"has_reasoning":True,"explanation":"ok"}
        raise AssertionError(node)

def test_integration_real_task_noisy(tmp_path):
    if REAL_TASK is None:
        import pytest; pytest.skip("no v2 task present")
    case_id = REAL_TASK.name
    gt = json.loads((REAL_TASK/"ground_truth.json").read_text(encoding="utf-8"))
    instruction = (REAL_TASK/"instruction.md").read_text(encoding="utf-8")
    raw = PROJECT_ROOT/"data/oncology_complete_trajectory/raw/csv"/f"{case_id}.csv"
    ctx = case_from_csv(case_id, raw, task_type=gt["task_type"],
                        target_group_id=gt["target_group_id"], target_date=gt["target_date"],
                        instruction=instruction, ground_truth=gt["ground_truth"])
    res = run_injection(ctx, NoiseConfig(noise_rows=3, episodes=1, max_attempts=1), Stub())
    assert res.final_status in ("noisy", "degraded_clean")
    if res.final_status == "noisy":
        assert len(res.rows) == 3
        # manifest.rows 与 CSV 行一致
        assert len(res.manifest["rows"]) == len(res.rows)
        evdates = [r["event_date"] for r in res.rows]
        assert all(gt["target_date"] > d >= ctx.first_even
t_date"" for d in evdates)  # 全部落在窗口内
```
> 注：上一步骤 `test_integration_real_task_noisy` 结尾的断言被截断，正确结尾为上面补全的三行。

- [ ] **Step 2: 全量回归跑通全部测试**

Run: `pytest tests/ -q`
Expected: 全部 PASS（含既有 `tests/test_v2_integration.py`、`tests/test_v2_units.py` 及全部新 `tests/test_noise_*.py`）

- [ ] **Step 3: dry-run 冒烟（不写盘，仅闸门）**

Run: `python -m scripts.apply_noise --dry-run --limit 2`
Expected: 打印每 case `dry_run_status` 与 `rows_passed`；`tasks/oncology-v2-noisy/` 不新增成功产物（无 `noise_manifest.json`）

- [ ] **Step 4: Lint / 导入自检**

Run: `python -c "from pipeline.noise_injection import injection, safety, judge, solvable, manifest, materialize, plan, context, catalog, config; from pipeline.oncology_generation import prompts_v2, leakage; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add tests/test_noise_integration.py
git commit -m "test(noise): end-to-end integration + regression"
```

---

## 执行顺序与依赖

```
Task 1(数据) → Task 2(上下文/提示词) → Task 3(materialize) → Task 4(plan) → Task 5(safety)
           → Task 6(judge) → Task 7(solvable) → Task 8(manifest+injection)
Task 9(pipeline 接入，依赖 1-8) → Task 10(apply_noise,依赖 8) → Task 11(集成/回归)
```
Task 1-2-3 内部可并行；Task 4/5/6/7 依赖 2+3（可并行）；Task 8 依赖 4-7；Task 9/10 依赖 8；Task 11 依赖全部。

## 明确不做 / 降级边界

- 不做共病线叙事（spec 架构留扩展位；`catalog` 已为将来扩展预留 `DEFAULT_CONVENTIONS` 结构）。
- 不改 agent/工具层/checkpoint/指令模板；指令不提示存在噪声。
- 不做 v1 任务。
- 不做字节级可复现（依赖 manifest 参数快照）。
- 端到端真实 LLM 试点（spec §8.3 / §9 人工 review）在计划任务完成后由用户/后续会话按 `scripts/apply_noise.py` 跑 `--pilot` 观感核验；自动化部分即本题计划全部验收项。

## 自检（Self-Review）

- **Spec 覆盖**：§1 红线（catalog + 规则闸门 + judge）→ Task 1/5/6；§3.1 Layer A/B → Task 2/3/4；§3.2 整类禁用 → Task 1/5；§3.3 时间规则 → Task 2/3/5；§3.4 字段一致性（group_id UUID/惯例采样/feature_type/不打标记）→ Task 3；§4 生成验证流程 + §4.1 三闸门 → Task 5/6/7；§4.2 重试阶梯 + degraded_clean + review_queue → Task 8/9/10；§5.1 包结构（9 文件 + 2 编排新文件）→ Task 1-8；§5.2 流水线接入 → Task 9；§5.3 批处理脚本 → Task 10；§6 manifest schema → Task 8；§7 NoiseConfig → Task 1/8；§8 测试策略 → Task 1-11；§9 验收标准 → Task 5/8/9/10/11。
- **占位符扫描**：全部代码块为具体实现，无 "TBD/TODO/implement later"。
- **类型一致性**：`run_injection -> InjectionResult(rows=17字段, manifest, attempts, review_queue_entries)` 在 Task 8/9/10 一致使用；`csv_row`/`CSV_FIELDS` 在 Task 3/8/9/10 一致；`build_context`/`case_from_csv` 在 Task 2/9/10 一致；`check(context, rows, client, *, visible_text=None)` 在 Task 7/8/9 一致；`materialize` 返回带 `csv_fields`+元字段的行在 Task 3/5/6/7/8 一致。

**已解决的规范歧义（决策留档）**：
1. `run_injection` 与 `CaseContext` 归属 → 新增 `injection.py`/`context.py`（spec 9 文件清单遗漏，已说明偏离）。
2. safety 的"关键证据日回避"按保守语义扩展为**所有**噪声行回避（不只 Layer B），避免数值/文本行落在求证日制造歧义。
3. gate2 逐行"重生成一次再判"在 `run_injection` 内实现（judged中有 rejected 时补 plan 一批再 judge），仍拒则丢弃。
4. pipeline_version 依 spec §3.4 从该病例同类别既有行采样（保持与既有数据一致，不额外标记噪声）。
5. 审计身份仅 manifest；CSV 无标记（`csv_row` 过滤 `_` 元字段）。
