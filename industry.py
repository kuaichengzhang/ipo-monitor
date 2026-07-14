"""行业分类工具 —— 基于公司名关键词识别医疗健康板块。

分类逻辑:
  1. 港交所 markers 含"18A"标记 -> 必为生物科技公司(18A章仅针对未盈利生物科技)
  2. 公司名中文关键词匹配（药/生物/医疗/健康/中药等）
  3. 港交所英文关键词匹配（Pharma/Biotech/Medical/Therapeutics等）

申万二级行业映射:
  化学制药 / 生物制品 / 医疗器械 / 医疗服务 / 中药
"""
from __future__ import annotations

# 医疗健康子行业关键词（按优先级排序，先匹配先返回）
HEALTHCARE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("中药", ["中药", "中成药", "本草", "同仁堂", "片仔癀", "云南白药", "堂"]),
    ("生物制品", ["生物", "疫苗", "基因", "细胞", "免疫", "核酸", "抗体", "蛋白",
                  "百济", "信达", "君实", "和黄", "荣昌",
                  "biotech", "biolog", "vaccine", "gene", "cell", "immuno",
                  "antibod", "protein", "therapeut", "bio-"]),
    ("医疗器械", ["医疗器", "医疗设", "器械", "影像", "诊断试剂", "体外诊断",
                  "迈瑞", "联影", "微创", "乐普",
                  "microport", "mindray", "medical device",
                  "medical instrum", "ivd", "diagnost"]),
    ("医疗服务", ["医疗服务", "医院", "诊所", "体检", "健康", "保健", "养老",
                  "CRO", "CDMO", "临床研究", "医药研发", "化成", "康龙", "药明",
                  "hospital", "clinic", "healthcare", "health care", "health ",
                  "life scien", "medical service"]),
    ("化学制药", ["制药", "药业", "医药", "化学药", "原料药", "制剂",
                  "pharma", "pharmac", "drug", "medicin", "chemical"]),
]

# 通用医疗关键词（兜底，归类为"其他医疗"）
HEALTHCARE_FALLBACK = ["医疗", "medical", "med ", "药", "pharma", "bio"]


def classify_industry(company_name: str, markers: list[str] | None = None) -> tuple[str, str, bool]:
    """根据公司名和标记位判断行业。

    Returns:
        (industry, sub_industry, is_18a)
        - 非医疗公司返回 ("", "", False)
        - 医疗公司返回 ("医疗健康", 子行业, True/False)
    """
    name = (company_name or "").strip().lower()
    markers = markers or []

    # 港交所 18A 标记 —— 18A章仅针对未盈利生物科技公司，必为医疗
    is_18a = any("18A" in m or "未盈利生物科技" in m for m in markers)

    # 18A 公司即使名字没匹配到关键词，也一定是生物科技
    if is_18a and not name:
        return ("医疗健康", "生物制品", True)

    if not name and not is_18a:
        return ("", "", False)

    # 按子行业关键词匹配
    for sub_industry, keywords in HEALTHCARE_KEYWORDS:
        for kw in keywords:
            if kw.lower() in name:
                return ("医疗健康", sub_industry, is_18a)

    # 18A 公司名字没匹配到，但 18A 章必为生物科技
    if is_18a:
        return ("医疗健康", "生物制品", True)

    # 兜底匹配
    for kw in HEALTHCARE_FALLBACK:
        if kw.lower() in name:
            return ("医疗健康", "其他医疗", is_18a)

    return ("", "", False)


def is_healthcare(company_name: str, markers: list[str] | None = None) -> bool:
    """快速判断是否为医疗健康公司。"""
    industry, _, _ = classify_industry(company_name, markers)
    return industry == "医疗健康"
