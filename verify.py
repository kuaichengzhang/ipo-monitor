"""数字校验器 —— 机器整篇写作的防编造闸门。

原理:拆解文章里出现的每一个数字,必须能在招股书原文(提取的页面文本)里找到。
找不到 = 疑似编造 = 整篇不通过,输出违规清单。

这是可编程验证,不依赖生成模型的自觉。配合规格铁律(每个数字挂页码)使用:
先查"数字在不在原文",再由人抽查"页码对不对"。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 从文本里抽"有意义的数字":含小数/千分位的金额、百分比、年份
_NUM_RE = re.compile(r"\d[\d,,]*(?:\.\d+)?")

# 这些数字不需要出现在招股书里(文档自身结构/日期/页码引用)
_IGNORABLE = re.compile(r"^(?:p|P|页|第)")


def _canon(num: str) -> str:
    """规范化:去千分位逗号。'1,504.4' -> '1504.4'"""
    return num.replace(",", "").replace(",", "")


def numbers_in(text: str) -> set[str]:
    return {_canon(m.group(0)) for m in _NUM_RE.finditer(text)}


@dataclass
class VerifyReport:
    ok: bool
    checked: int = 0
    violations: list[str] = field(default_factory=list)   # 原文中找不到的数字
    ignored: int = 0

    def summary(self) -> str:
        if self.ok:
            return f"✓ 校验通过:{self.checked} 个数字全部能在招股书原文中找到"
        return (f"✗ 校验不通过:{len(self.violations)} 个数字在原文中找不到(疑似编造/换算):"
                + ", ".join(sorted(self.violations)[:10]))


def verify_numbers(article: str, source_pages: list,
                   extra_allowed: set[str] | None = None) -> VerifyReport:
    """article 中的每个数字必须存在于 source_pages 任一页文本中。

    豁免:页码引用(含区间 p.42–46)、单个数字序号、extra_allowed 白名单。
    白名单用于有自身溯源的元数据数字(如股票代码来自交易所列表数据、非招股书)。
    """
    src = " ".join(getattr(p, "text", "") or "" for p in source_pages)
    src_nums = numbers_in(src)

    # 页码引用中的数字豁免(单页 p.22 与区间 p.42–46 都豁免)
    cite_nums = {_canon(m) for m in re.findall(r"[pP]\.\s*(\d+)", article)}
    for a, b in re.findall(r"[pP]\.\s*(\d+)\s*[–—-]\s*(\d+)", article):
        cite_nums.add(_canon(a)); cite_nums.add(_canon(b))
    allowed = {_canon(x) for x in (extra_allowed or set())}

    report = VerifyReport(ok=True)
    for raw in {_canon(m.group(0)) for m in _NUM_RE.finditer(article)}:
        if (raw in cite_nums or raw in allowed) and raw not in src_nums:
            report.ignored += 1
            continue
        if len(raw) == 1:          # 序号 1/2/3 豁免
            report.ignored += 1
            continue
        report.checked += 1
        if raw not in src_nums:
            report.violations.append(raw)
    report.ok = not report.violations
    return report
