"""阶段归一化。

四个交易所的审核状态叫法各不相同(港交所"招股/配发",A股"已受理/上市委会议通过/
提交注册/注册生效")。架子把它们统一映射到一套 canonical 阶段,这样:
- Paodekuai 的触发点「过会 + PHIP」在四所是同一个概念(=PASSED);
- 分诊卡、网站可以按统一阶段筛选、排序、上色。

这是"架子扩得动"的关键:加一个交易所 = 加一张 {原始状态 -> 统一阶段} 映射表。
"""
from __future__ import annotations

# —— 统一阶段(按管线先后)——
ACCEPTED = "申报受理"
INQUIRED = "已问询/回复"
HEARING = "上会/聆讯"
PASSED = "过会/通过"          # ← Paodekuai 的触发阶段(A股过会 ≈ 港交所 PHIP 发布)
SUBMITTED_REG = "提交注册"
EFFECTIVE = "注册生效/招股"
LISTED = "已上市"
SUSPENDED = "中止"
TERMINATED = "终止/退回/未通过"
UNKNOWN = "未知"

# 供网站排序用的阶段顺序
STAGE_ORDER = [
    ACCEPTED, INQUIRED, HEARING, PASSED, SUBMITTED_REG,
    EFFECTIVE, LISTED, SUSPENDED, TERMINATED, UNKNOWN,
]

# Paodekuai 的选题触发阶段:过会及其后、尚未上市之前
TRIGGER_STAGES = {PASSED, SUBMITTED_REG, EFFECTIVE}

# —— 港交所原始状态 -> 统一阶段 ——
_HKEX_MAP = {
    "上市公告": EFFECTIVE,
    "招股(已刊发招股章程)": EFFECTIVE,
    "已配发结果": LISTED,
    "聆讯后资料集(PHIP)": PASSED,    # PHIP 适配器接上后用
    "申请版本": ACCEPTED,
}

# —— 上交所(科创板/主板)原始状态 -> 统一阶段 ——
# 状态词取自上交所发行上市审核项目动态的口径
_SSE_MAP = {
    "已受理": ACCEPTED,
    "已问询": INQUIRED,
    "已回复": INQUIRED,
    "补充审核": INQUIRED,
    "补充审核已问询": INQUIRED,
    "补充审核已回复": INQUIRED,
    "上市委审议": HEARING,
    "暂缓审议": HEARING,
    "上市委会议通过": PASSED,
    "通过": PASSED,
    "上市委会议未通过": TERMINATED,
    "未通过": TERMINATED,
    "提交注册": SUBMITTED_REG,
    "注册生效": EFFECTIVE,
    "注册结果": EFFECTIVE,
    "不予注册": TERMINATED,
    "终止注册": TERMINATED,
    "中止及财报更新": SUSPENDED,
    "中止": SUSPENDED,
    "终止": TERMINATED,
}

_MAPS = {
    "港交所": _HKEX_MAP,
    "上交所": _SSE_MAP,
    # 深交所:官方状态字典(接口 stageList 实测)与上交所口径一致,另有复审/终止细分
    "深交所": {
        **_SSE_MAP,
        "上市委复审会议通过": PASSED,
        "上市委复审会议未通过": TERMINATED,
        "暂缓审议": HEARING,
        "不予注册": TERMINATED,
        "终止(审核不通过)": TERMINATED,
        "终止(撤回)": TERMINATED,
        "终止(未在规定时限内回复)": TERMINATED,
    },
    # 北交所:P码字典(页面筛选器实测);"核准"为精选层时期口径
    "北交所": {
        **_SSE_MAP,
        "上市委会议暂缓": HEARING,
        "报送证监会": SUBMITTED_REG,
        "证监会注册": EFFECTIVE,
        "注册": EFFECTIVE,
        "核准": EFFECTIVE,
        "注册结果": EFFECTIVE,
        "不予注册": TERMINATED,
        "不予核准": TERMINATED,
    },
}


def normalize_stage(exchange: str, raw_status: str) -> str:
    """(交易所, 原始状态) -> 统一阶段。找不到则原样归 UNKNOWN,并可日志告警。"""
    table = _MAPS.get(exchange, {})
    if raw_status in table:
        return table[raw_status]
    # 容错:原始状态里包含某个关键词
    for key, stage in table.items():
        if key in raw_status:
            return stage
    return UNKNOWN


def is_trigger(stage: str) -> bool:
    return stage in TRIGGER_STAGES
