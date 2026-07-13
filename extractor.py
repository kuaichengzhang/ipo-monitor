"""招股书数字提取 —— 带页码出处。

【铁律(规格书 v0.2)】
每个数字必须挂出处 `【招股书 p.XX】`。**找不到出处的数字,不是编一个填上,
而是留空标红 `[缺出处·待核]`。**

本模块的设计就是把这条焊死:
- 唯一的数值来源是 PDF 页面的真实文本(Evidence.page 必填,由文本所在页决定);
- 没有任何"推断""补全""默认值"路径;
- 提取失败 -> 返回 MISSING 标记,由下游原样呈现为待核项。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

MISSING = "[缺出处·待核]"


@dataclass
class Evidence:
    """一条带出处的证据。value 与 page 同生共死:没有 page 就不该有 value。"""
    value: str          # 原文中的数值/表述(原样保留,不做换算)
    page: int           # 页码(1-based),必填
    snippet: str        # 数值所在的原文片段,便于人工核对
    label: str = ""     # 指标名

    def cite(self) -> str:
        return f"【招股书 p.{self.page}】"

    def render(self) -> str:
        return f"{self.value} {self.cite()}"


@dataclass
class Metric:
    """一个指标的提取结果。未命中即 MISSING,绝不填充。"""
    name: str
    evidences: list[Evidence] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.evidences)

    def render(self) -> str:
        if not self.found:
            return MISSING
        return "; ".join(e.render() for e in self.evidences)


@dataclass
class Page:
    number: int         # 1-based
    text: str


# —— 数值正则 ——
# 中文财报常见:1,234.56 万元 / 亿元 / 元;百分比 12.3%;负数 (1,234) 或 -1,234
NUM = r"[-−(]?\d[\d,,]*(?:\.\d+)?\)?"
PCT = r"[-−]?\d+(?:\.\d+)?\s*%"

# 指标关键词 -> 正则(在含关键词的句子里找数值)
# 关键词取自规格书「关键数字快照」的 14 项
# 覆盖三种语体:简体(A股招股书)/ 繁体(港股中文版)/ 英文(港股英文版)
# 实测教训(基本半导体 2026-07):港股中文版可能用 CID 字体(无 ToUnicode),
# 中文提取为空 —— 见 cid_trap_ratio();此时应改用英文版并标注「英文版」。
METRIC_PATTERNS: dict[str, list[str]] = {
    "营收": [r"营业收入", r"收入总额", r"总收入", r"營業收入", r"收益", r"\brevenue\b"],
    "净利润/净亏损": [r"净利润", r"净亏损", r"年内(?:利润|亏损)", r"淨利潤", r"淨虧損", r"虧損",
                r"net (?:loss|profit|income)", r"loss for the year", r"loss before tax"],
    "经调整净利润/亏损": [r"经调整(?:净)?(?:利润|亏损)", r"非国际财务报告准则", r"經調整", r"非國際財務報告準則",
                  r"adjusted net (?:loss|profit)", r"non-IFRS"],
    "毛利率": [r"毛利率", r"gross (?:profit )?margin"],
    "研发投入/研发费用率": [r"研发(?:费用|投入|开支)", r"研發(?:費用|投入|開支)", r"R&D", r"research and development"],
    "客户集中度": [r"前五(?:大|名)客户", r"第一大客户", r"最大客户", r"五大客戶", r"最大客戶",
              r"five largest customers", r"largest customer"],
    "产能利用率": [r"产能利用率", r"產能利用率", r"utili[sz]ation rate"],
    "政府补助/非经常性损益": [r"政府补助", r"非经常性损益", r"政府補助", r"其他收入及收益",
                   r"government (?:grants|subsidies)"],
    "经营活动现金流": [r"经营活动(?:产生|所用)的?现金流量净额", r"經營活動", r"经营活动现金流",
               r"cash (?:used in|generated from|flows? from) operating activities"],
    "单价/ASP": [r"平均(?:售价|单价)", r"平均(?:售價|單價)", r"\bASP\b", r"average selling price"],
    "市占率/排名": [r"市场份额", r"市占率", r"排名第", r"市場份額", r"第[一二三四五六七八九十]",
              r"market share", r"\brank(?:ed|ing)?\b"],
    "关联交易": [r"关联交易", r"关联方(?:销售|采购)", r"關聯交易", r"related part(?:y|ies) transactions"],
    "拟募资额": [r"募集资金", r"拟募集", r"所得款项净额", r"所得款項淨額", r"net proceeds"],
    "扭亏时间表": [r"预计.{0,12}(?:实现盈利|扭亏|盈亏平衡)", r"盈亏平衡", r"盈虧平衡", r"扭虧",
              r"path to profitability", r"breakeven", r"achieve profitability"],
}

# 会计准则 & 报告期(规格书:必标)
STANDARD_PATTERNS = [
    (r"国际财务报告准则|International Financial Reporting Standards|IFRS", "IFRS"),
    (r"企业会计准则|中国企业会计准则", "中国企业会计准则(PRC GAAP)"),
    (r"香港财务报告准则|HKFRS", "HKFRS"),
]

# 市占率口径限定语的委托机构(规格书:必须原文照录 + 注明委托研究)
RESEARCH_HOUSES = [r"弗若斯特沙利文", r"灼识", r"灼識", r"[Cc][Ii][Cc]", r"Frost\s*&\s*Sullivan", r"Omdia", r"IDC", r"赛迪", r"賽迪"]


def normalize_text(text: str) -> str:
    """归一化:去掉中文字符间被 PDF 提取塞入的空格(实测港股 PDF 会出现"全 球發 售")。"""
    # CJK 字符之间的空白直接删除;其余空白压成单个空格
    cjk = "\\u4e00-\\u9fff\\u3000-\\u303f\\uff00-\\uffef"
    text = re.sub(rf"(?<=[{cjk}])[ \\u00a0]+(?=[{cjk}])", "", text)
    return re.sub(r"[ \u00a0]{2,}", " ", text)


def cid_trap_ratio(pages: list["Page"], sample: int = 8) -> float:
    """检测 CID 字体陷阱:返回抽样页的 CJK 字符占比。

    实测(基本半导体港股中文版):正文用 Adobe-CNS1 CID 字体且无 ToUnicode 映射,
    任何库都提不出中文(只剩数字/标点)。若占比≈0 而文档应为中文,说明踩坑,
    应改用英文版提取(引用标注「英文版」)或走 OCR。
    """
    mid = pages[len(pages)//4 : len(pages)//4 + sample] or pages[:sample]
    text = "".join(p.text or "" for p in mid)
    if not text:
        return 0.0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return cjk / max(len(text), 1)


def _sentences(text: str) -> Iterable[str]:
    text = normalize_text(text)
    # 中文句读 + 英文句号断句(英文按 ". " 切,避免小数点误切)
    for s in re.split(r"[。;;\n]|(?<=[a-z\)])\.\s+(?=[A-Z])", text):
        s = (s or "").strip()
        if s:
            yield s


def extract_metric(pages: list[Page], metric_name: str, patterns: list[str],
                   max_hits: int = 6) -> Metric:
    """在所有页里找含关键词且含数值的句子,记录数值 + 页码 + 原文片段。

    只从真实页面文本提取;不做任何推断或补全。
    """
    m = Metric(name=metric_name)
    kw = re.compile("|".join(patterns), re.IGNORECASE)

    for page in pages:
        if not page.text:
            continue
        for sent in _sentences(page.text):
            if not kw.search(sent):
                continue
            # 句中必须真的出现"带单位/带货币/带百分号"的数值,否则不算证据(宁缺毋滥)
            valre = (f"{PCT}"
                     f"|(?:RMB|HK\\$|US\\$|USD|人民幣|人民币|港元)\\s*{NUM}\\s*(?:million|billion|thousand|百萬|百万|億|亿)?"
                     f"|{NUM}\\s*(?:million|billion|thousand)"
                     f"|{NUM}\\s*(?:亿元|万元|亿|万|元|億元|萬元|億|萬)"
                     f"|\\b(?:19|20)\\d{{2}}\\b(?:年|年度)?")
            vals = [v.strip() for v in re.findall(valre, sent) if v.strip()]
            if not vals:
                continue
            snippet = sent if len(sent) <= 160 else sent[:157] + "…"
            m.evidences.append(Evidence(
                value=", ".join(vals[:6]),
                page=page.number,
                snippet=snippet,
                label=metric_name,
            ))
            if len(m.evidences) >= max_hits:
                return m
    return m


def extract_accounting_standard(pages: list[Page]) -> Metric:
    """会计准则(规格书:必标,防 A股/H股口径打架)。"""
    m = Metric(name="会计准则")
    for page in pages:
        for pat, label in STANDARD_PATTERNS:
            if re.search(pat, page.text or ""):
                sent = next((s for s in _sentences(page.text) if re.search(pat, s)), "")
                m.evidences.append(Evidence(
                    value=label, page=page.number,
                    snippet=(sent[:157] + "…") if len(sent) > 160 else sent,
                    label="会计准则",
                ))
                return m
    return m


def extract_market_share_claims(pages: list[Page], max_hits: int = 5) -> Metric:
    """市占率/排名 claim —— 必须连同口径限定语和委托机构原文照录。

    规格书硬约束:'全球第一'类表述的口径(产品范围/地域/指标口径)必须原文照录,
    并注明是哪家委托研究(弗若斯特沙利文/灼识/CIC 等)。
    这里不改写、不概括,直接把原句作为证据留下,交人核对。
    """
    m = Metric(name="市占率/排名(原文照录)")
    rank_re = re.compile(
        r"(第[一二三四五六七八九十]|排名第|市场份额|市占率|市場份額|占.{0,4}%"
        r"|market share|\brank(?:ed|ing)?\b|industry consultant|according to (?:Frost|CIC|Omdia))",
        re.IGNORECASE)
    house_re = re.compile("|".join(RESEARCH_HOUSES))
    for page in pages:
        for sent in _sentences(page.text or ""):
            if not rank_re.search(sent):
                continue
            has_house = bool(house_re.search(sent))
            # 原句照录;标注是否在同句出现委托机构(未出现则提示需回溯口径出处)
            note = "" if has_house else "  ⚠口径/委托机构未在同句出现,需回溯"
            snippet = sent if len(sent) <= 200 else sent[:197] + "…"
            m.evidences.append(Evidence(
                value=f"「{snippet}」{note}",
                page=page.number, snippet=snippet, label="市占率/排名",
            ))
            if len(m.evidences) >= max_hits:
                return m
    return m


def extract_all(pages: list[Page]) -> dict[str, Metric]:
    """按规格书「关键数字快照」提取全部指标。未命中的保持 MISSING。"""
    out: dict[str, Metric] = {}
    for name, pats in METRIC_PATTERNS.items():
        if name == "市占率/排名":
            continue
        out[name] = extract_metric(pages, name, pats)
    out["市占率/排名"] = extract_market_share_claims(pages)
    out["会计准则"] = extract_accounting_standard(pages)
    return out


def load_pdf(path: str, max_pages: Optional[int] = None) -> list[Page]:
    """读 PDF -> 页文本列表(页码 1-based,即引用时的 p.XX)。"""
    import pdfplumber

    pages: list[Page] = []
    with pdfplumber.open(path) as pdf:
        for i, p in enumerate(pdf.pages, start=1):
            if max_pages and i > max_pages:
                break
            pages.append(Page(number=i, text=p.extract_text() or ""))
    return pages
