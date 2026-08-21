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
    for terms in FORBIDDEN_TERMS_BY_CATEGORY.values():
        for term in terms:
            if term.casefold() in s.casefold():
                hits.append(f"禁用术语:{term}")
    return hits
