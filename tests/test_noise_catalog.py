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
