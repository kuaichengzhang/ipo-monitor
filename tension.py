"""张力打分 —— 按规格书 v0.2 的「张力信号表」。

机器对 11 个主题逐项打分,越过阈值即入选候选(封顶 5),分最高的 3 个预选为支柱。
**机器只陈述"数字反差在哪",不下判断、不定性。**措辞一律是"提取到的数字反差",
不是"这公司有问题"。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from extractor import Metric, Evidence

MAX_CANDIDATES = 5
PRESELECT = 3


@dataclass
class TensionCandidate:
    theme: str
    score: int
    signals: list[str] = field(default_factory=list)   # 中性陈述的反差
    evidences: list[Evidence] = field(default_factory=list)

    def render(self) -> str:
        cites = " ".join(sorted({e.cite() for e in self.evidences}))
        sig = "; ".join(self.signals)
        return f"{self.theme}(张力分 {self.score}):{sig} {cites}"


def _nums(text: str) -> list[float]:
    out = []
    for tok in re.findall(r"[-−]?\d+(?:\.\d+)?", text.replace(",", "").replace(",", "")):
        try:
            out.append(float(tok.replace("−", "-")))
        except ValueError:
            pass
    return out


def _pcts(evs: list[Evidence]) -> list[float]:
    vals = []
    for e in evs:
        for tok in re.findall(r"([-−]?\d+(?:\.\d+)?)\s*%", e.value + " " + e.snippet):
            try:
                vals.append(float(tok.replace("−", "-")))
            except ValueError:
                pass
    return vals


def score_tensions(metrics: dict[str, Metric]) -> list[TensionCandidate]:
    """按信号表打分。每条 signal 都是对数字反差的中性陈述。"""
    cands: list[TensionCandidate] = []

    def get(name: str) -> Metric:
        return metrics.get(name, Metric(name=name))

    # —— 盈利结构 ——
    profit = get("净利润/净亏损")
    adj = get("经调整净利润/亏损")
    subsidy = get("政府补助/非经常性损益")
    turn = get("扭亏时间表")
    c = TensionCandidate("盈利结构", 0)
    if profit.found and any("亏" in e.snippet for e in profit.evidences):
        c.score += 2
        c.signals.append("报告期存在亏损表述")
        c.evidences += profit.evidences[:2]
    if turn.found:
        c.score += 2
        c.signals.append("招股书披露了扭亏/盈亏平衡时间表")
        c.evidences += turn.evidences[:1]
    if subsidy.found and profit.found:
        c.score += 1
        c.signals.append("同时出现净利润与政府补助/非经常性损益表述(占比需人工核)")
        c.evidences += subsidy.evidences[:1]
    if adj.found:
        c.score += 1
        c.signals.append("披露了经调整口径(与IFRS口径差异需说明)")
        c.evidences += adj.evidences[:1]
    if c.score:
        cands.append(c)

    # —— 毛利率 ——
    gm = get("毛利率")
    c = TensionCandidate("毛利率", 0)
    if gm.found:
        vals = _pcts(gm.evidences)
        if len(vals) >= 2:
            spread = max(vals) - min(vals)
            if spread >= 10:
                c.score += 2
                c.signals.append(f"提取到的毛利率数值区间跨度较大({min(vals)}%–{max(vals)}%)")
            elif spread >= 3:
                c.score += 1
                c.signals.append(f"毛利率数值存在变动({min(vals)}%–{max(vals)}%)")
            c.evidences += gm.evidences[:3]
        else:
            c.score += 1
            c.signals.append("提取到毛利率表述(逐年对比需人工核)")
            c.evidences += gm.evidences[:2]
    if c.score:
        cands.append(c)

    # —— 客户集中度(阈值:前五大>50% 或 第一大>30%)——
    cust = get("客户集中度")
    c = TensionCandidate("客户集中度", 0)
    if cust.found:
        vals = _pcts(cust.evidences)
        top = max(vals) if vals else 0
        if top >= 50:
            c.score += 3
            c.signals.append(f"客户集中度相关数值达 {top}%(规格书阈值:前五大>50%)")
        elif top >= 30:
            c.score += 2
            c.signals.append(f"客户集中度相关数值达 {top}%(规格书阈值:第一大>30%)")
        elif vals:
            c.score += 1
            c.signals.append(f"提取到客户集中度数值(最高 {top}%)")
        else:
            c.score += 1
            c.signals.append("提取到客户集中表述")
        c.evidences += cust.evidences[:3]
    if c.score:
        cands.append(c)

    # —— 产能与扩产 ——
    cap = get("产能利用率")
    raise_ = get("拟募资额")
    c = TensionCandidate("产能与扩产", 0)
    if cap.found:
        vals = _pcts(cap.evidences)
        low = min(vals) if vals else None
        if low is not None and low < 90:
            c.score += 2
            c.signals.append(f"产能利用率提取值低于满产({low}%)")
        else:
            c.score += 1
            c.signals.append("提取到产能利用率数值")
        c.evidences += cap.evidences[:2]
        if raise_.found and re.search(r"扩产|产能建设|新增产能|扩建", " ".join(e.snippet for e in raise_.evidences)):
            c.score += 2
            c.signals.append("同时出现:产能利用率未满 + 募资用于扩产(反差需人工核实口径)")
            c.evidences += raise_.evidences[:1]
    if c.score:
        cands.append(c)

    # —— 研发投入 ——
    rd = get("研发投入/研发费用率")
    c = TensionCandidate("研发投入", 0)
    if rd.found:
        vals = _pcts(rd.evidences)
        top = max(vals) if vals else None
        if top is not None and (top >= 30 or top <= 5):
            c.score += 2
            c.signals.append(f"研发费用率提取值偏离常见区间({top}%);与招股书所列同行均值对比需人工核")
        else:
            c.score += 1
            c.signals.append("提取到研发投入数值")
        c.evidences += rd.evidences[:2]
    if c.score:
        cands.append(c)

    # —— 市场地位(口径必须原文照录)——
    ms = get("市占率/排名")
    c = TensionCandidate("市场地位", 0)
    if ms.found:
        c.score += 2
        narrow = [e for e in ms.evidences if "⚠" in e.value]
        c.signals.append("招股书出现排名/市占率表述(口径限定语与委托机构须原文照录)")
        if narrow:
            c.score += 1
            c.signals.append(f"其中 {len(narrow)} 条未在同句给出委托机构/口径,需回溯原文")
        c.evidences += ms.evidences[:3]
    if c.score:
        cands.append(c)

    # —— 关联交易 ——
    rel = get("关联交易")
    c = TensionCandidate("关联交易", 0)
    if rel.found:
        vals = _pcts(rel.evidences)
        top = max(vals) if vals else 0
        c.score += 2 if top >= 20 else 1
        c.signals.append(
            f"提取到关联交易数值(最高 {top}%)" if vals else "提取到关联交易表述")
        c.evidences += rel.evidences[:2]
    if c.score:
        cands.append(c)

    # —— 募资与融资动机 ——
    cf = get("经营活动现金流")
    c = TensionCandidate("募资与融资动机", 0)
    if cf.found and any(re.search(r"净流出|为负|-", e.snippet) for e in cf.evidences):
        c.score += 2
        c.signals.append("经营活动现金流出现净流出/负值表述")
        c.evidences += cf.evidences[:2]
    if raise_.found:
        c.score += 1
        c.signals.append("披露拟募资额与用途(占总资产比例需人工核)")
        c.evidences += raise_.evidences[:1]
    if c.score:
        cands.append(c)

    # —— 商业模式(单价/ASP)——
    asp = get("单价/ASP")
    c = TensionCandidate("商业模式", 0)
    if asp.found:
        vals = _nums(" ".join(e.value for e in asp.evidences))
        if len(vals) >= 2 and max(vals) > 0 and min(vals) / max(vals) < 0.7:
            c.score += 2
            c.signals.append(f"提取到的单价/ASP数值存在明显落差({min(vals)}–{max(vals)})")
        else:
            c.score += 1
            c.signals.append("提取到单价/ASP数值")
        c.evidences += asp.evidences[:2]
    if c.score:
        cands.append(c)

    # —— 增长 ——
    rev = get("营收")
    c = TensionCandidate("增长", 0)
    if rev.found:
        c.score += 1
        c.signals.append("提取到营收数值(逐年增速需人工核)")
        c.evidences += rev.evidences[:2]
        if profit.found and any("亏" in e.snippet for e in profit.evidences):
            c.score += 1
            c.signals.append("营收与亏损表述同时存在(增收与利润背离需人工核)")
    if c.score:
        cands.append(c)

    cands.sort(key=lambda x: x.score, reverse=True)
    return cands[:MAX_CANDIDATES]


def preselect_pillars(cands: list[TensionCandidate]) -> list[TensionCandidate]:
    return cands[:PRESELECT]
