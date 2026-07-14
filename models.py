"""数据模型:一条 IPO 申请/披露记录。

所有采集器(港/沪/深/北)最终都产出 Filing,喂给分诊卡和骨架草稿。
字段对应规格书 v0.2「分诊卡·身份区」。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


# 港交所公司名后缀标记位(规格书里要求识别)
HKEX_MARKERS = {
    "W": "同股不同权(WVR)",
    "B": "未盈利生物科技(18A)",
    "Z": "特殊目的收购公司(SPAC/18B)",
    "P": "特专科技·未商业化(18C)",
    "S": "第二上市",
}


def parse_hkex_markers(stock_name: str) -> tuple[str, list[str]]:
    """从港交所公司名尾部解析标记位。

    例:'MOMENTA GLOBAL LIMITED - W' -> ('MOMENTA GLOBAL LIMITED', ['同股不同权(WVR)'])
    多个标记会连写(如 '- B - W'),逐个解析。
    """
    name = stock_name.strip()
    markers: list[str] = []
    # 反复剥离尾部的 ' - X'(X 为单个大写标记字母)
    pattern = re.compile(r"\s*[-–]\s*([WBZPS])\s*$")
    while True:
        m = pattern.search(name)
        if not m:
            break
        markers.insert(0, HKEX_MARKERS[m.group(1)])
        name = name[: m.start()].rstrip()
    return name, markers


@dataclass
class Filing:
    # —— 身份区(所有交易所通用)——
    exchange: str                 # 港交所 / 上交所 / 深交所 / 北交所
    board: str                    # 主板 / GEM / 科创板 / 创业板 / 北交所
    company_name: str
    status: str                   # 各所原始状态词(招股/已受理/上市委会议通过...)
    stage: str = ""               # 归一化阶段(见 stages.py);由采集器填,跨所统一
    stock_code: Optional[str] = None
    sponsor: Optional[str] = None

    # —— 文档链接 ——
    prospectus_url: Optional[str] = None      # 招股书 / 招股章程
    announcement_url: Optional[str] = None    # 上市/申请公告
    allotment_url: Optional[str] = None       # 配发结果(港交所)
    phip_url: Optional[str] = None            # 聆讯后资料集(留给 PHIP 适配器)

    markers: list[str] = field(default_factory=list)  # 港交所 W/B/Z/P/S 等
    page_updated: Optional[str] = None        # 源页面标注的更新日期
    source_url: Optional[str] = None          # 抓取自哪个列表页

    # —— 行业标签(由 industry.py 填充) ——
    industry: str = ""                        # 一级行业: 医疗健康 / ""
    sub_industry: str = ""                    # 二级行业: 化学制药/生物制品/医疗器械/医疗服务/中药
    is_18a: bool = False                      # 港交所未盈利生物科技(18A)

    # —— 系统字段 ——
    first_seen: Optional[str] = None          # 本系统首次见到的时间(UTC ISO)
    last_seen: Optional[str] = None

    @property
    def uid(self) -> str:
        """稳定去重键:交易所 + 代码 + 公司名(招股书链接纳入,便于识别文档更新)。"""
        basis = "|".join([
            self.exchange,
            self.stock_code or "",
            self.company_name,
            self.prospectus_url or self.phip_url or "",
        ])
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["uid"] = self.uid
        return d


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ===== 财报披露模型 =====

@dataclass
class FinReport:
    """一条财报披露公告记录。"""
    exchange: str                 # 上交所 / 深交所 / 北交所 / 港交所
    company_name: str
    stock_code: str
    report_type: str              # 年报/半年报/一季报/三季报/业绩预告/业绩快报
    report_period: str = ""       # 报告期，如 "2026年半年度"
    title: str = ""
    announcement_date: str = ""   # YYYY-MM-DD
    announcement_url: str = ""
    source: str = ""              # CNINFO / HKEX

    # —— 行业标签(由 industry.py 填充) ——
    industry: str = ""
    sub_industry: str = ""
    is_18a: bool = False

    @property
    def uid(self) -> str:
        basis = "|".join([self.exchange, self.stock_code, self.report_type, self.report_period, self.title])
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["uid"] = self.uid
        return d
