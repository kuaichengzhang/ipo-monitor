"""港交所采集器。

已实现:HKEXNewListingInfoCollector —— 抓 www2.hkexnews.hk 的「New Listing
Information」表(服务端渲染 HTML,结构稳定)。这是招股/发行阶段的公司,带招股书
PDF 直链。解析逻辑已用真实页面数据在 tests/ 里测过。

待接线:HKEXAppProofCollector —— 更早的「申请版本 / 聆讯后资料集(PHIP)」源
(www1.hkexnews.hk/app/appindex.html)。该页由 JS 从一个 JSON 接口加载,需要先
从浏览器开发者工具的 Network 面板确认接口 URL,再照本文件同样的模式实现。骨架已留好。
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors.base import BaseCollector
from models import Filing, parse_hkex_markers, utc_now_iso
from stages import normalize_stage

NEW_LISTING_INFO_URLS = {
    "主板": "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=zh-cn",
    "GEM": "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/GEM?sc_lang=zh-cn",
}

_PDF_RE = re.compile(r"\.pdf($|\?)", re.I)
_UPDATED_RE = re.compile(r"Updated:\s*([0-9]{1,2}\s+\w+\s+[0-9]{4})", re.I)


def _first_pdf(cell) -> str | None:
    """从一个单元格里取第一个 .pdf 链接。"""
    if cell is None:
        return None
    for a in cell.find_all("a", href=True):
        if _PDF_RE.search(a["href"]):
            return a["href"]
    return None


def _find_listing_table(soup: BeautifulSoup):
    """找到表头含 Stock Code / Stock Name 的那张表(不依赖 class 名,抗改版)。"""
    for table in soup.find_all("table"):
        header_text = " ".join(
            th.get_text(" ", strip=True).lower()
            for th in table.find_all(["th", "td"], limit=6)
        )
        if "stock code" in header_text or "股份代号" in header_text or "股票代码" in header_text:
            return table
    return None


def parse_new_listing_info(html: str, board: str, source_url: str) -> list[Filing]:
    """解析「New Listing Information」页 -> list[Filing]。

    列:股份代号 | 公司名 | 上市公告 | 招股章程 | 配发结果
    """
    soup = BeautifulSoup(html, "lxml")

    updated = None
    m = _UPDATED_RE.search(soup.get_text(" ", strip=True))
    if m:
        updated = _fmt_hk_updated(m.group(1))

    table = _find_listing_table(soup)
    if table is None:
        return []

    filings: list[Filing] = []
    now = utc_now_iso()
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue  # 表头或分隔行
        code = cells[0].get_text(strip=True)
        raw_name = cells[1].get_text(" ", strip=True)
        if not code or not raw_name:
            continue
        if not re.fullmatch(r"\d{1,5}", code):
            continue  # 首列不是股份代号,跳过(防误吃表头)

        name, markers = parse_hkex_markers(raw_name)
        ann = _first_pdf(cells[2]) if len(cells) > 2 else None
        pros = _first_pdf(cells[3]) if len(cells) > 3 else None
        allot = _first_pdf(cells[4]) if len(cells) > 4 else None

        # 绝对化链接
        ann = urljoin(source_url, ann) if ann else None
        pros = urljoin(source_url, pros) if pros else None
        allot = urljoin(source_url, allot) if allot else None

        if pros:
            status = "招股(已刊发招股章程)"
        elif allot:
            status = "已配发结果"
        else:
            status = "上市公告"

        filings.append(Filing(
            exchange="港交所",
            board=board,
            stock_code=code,
            company_name=name,
            markers=markers,
            status=status,
            stage=normalize_stage("港交所", status),
            prospectus_url=pros,
            announcement_url=ann,
            allotment_url=allot,
            page_updated=updated,
            source_url=source_url,
            first_seen=now,
            last_seen=now,
        ))
    return filings


class HKEXNewListingInfoCollector(BaseCollector):
    name = "hkex_new_listing_info"

    def collect(self) -> list[Filing]:
        out: list[Filing] = []
        for board, url in NEW_LISTING_INFO_URLS.items():
            html = self.get(url)
            out.extend(parse_new_listing_info(html, board, url))
        return out


class HKEXAppProofCollector(BaseCollector):
    """申请版本 / 聆讯后资料集(PHIP)源 —— 已接通真实接口。

    数据源(经浏览器 Network 实测确认):
      AP 接口(申请版本):
        https://www1.hkexnews.hk/ncms/json/eds/appactive_app_sehk_c.json  (主板,中文名)
        https://www1.hkexnews.hk/ncms/json/eds/appactive_app_gem_c.json   (GEM,中文名)
      PHIP 接口(聆讯后资料集):
        https://www1.hkexnews.hk/ncms/json/eds/appactive_appphip_sehk_c.json  (主板,中文名)
        https://www1.hkexnews.hk/ncms/json/eds/appactive_appphip_gem_c.json   (GEM,中文名)

      港交所于 2026 年将 PHIP 公司从 AP 接口拆出,AP 接口 hasPhip 全部为 false,
      PHIP 公司需从 apphip 接口单独获取。

      纯 JSON,记录在 .app;每条:id(=文件夹号)、d(日期)、a(公司名)、hasPhip(是否已发PHIP)、
      ls/ps(文档数组,文档名在 nF/nS1,相对路径在 u1)。
    触发信号:hasPhip==true 即「过会/PHIP已发」= 选题触发点。
    PDF 链接 = https://www1.hkexnews.hk/app/ + u1。
    """
    name = "hkex_app_phip"

    APP_ACTIVE_URLS = {
        "主板": "https://www1.hkexnews.hk/ncms/json/eds/appactive_app_sehk_c.json",
        "GEM": "https://www1.hkexnews.hk/ncms/json/eds/appactive_app_gem_c.json",
    }
    PHIP_URLS = {
        "主板": "https://www1.hkexnews.hk/ncms/json/eds/appactive_appphip_sehk_c.json",
        "GEM": "https://www1.hkexnews.hk/ncms/json/eds/appactive_appphip_gem_c.json",
    }

    def collect(self) -> list[Filing]:
        out: list[Filing] = []
        # AP 接口(申请版本)
        for board, url in self.APP_ACTIVE_URLS.items():
            data = json.loads(self.get(url))
            for rec in data.get("app", []):
                out.append(map_app_record(rec, board))
        # PHIP 接口(聆讯后资料集) —— 2026年港交所拆分后需单独请求
        for board, url in self.PHIP_URLS.items():
            data = json.loads(self.get(url))
            for rec in data.get("app", []):
                out.append(map_app_record(rec, board))
        return out


HKEX_APP_PREFIX = "https://www1.hkexnews.hk/app/"


def _doc_url(entries, keywords: list[str]) -> str | None:
    """在文档数组里找名称含关键词的条目,返回其绝对 PDF 链接。"""
    for e in entries or []:
        label = (e.get("nF") or "") + (e.get("nS1") or "") + (e.get("nS2") or "")
        if any(k in label for k in keywords):
            u = e.get("u1")
            if u:
                return HKEX_APP_PREFIX + u
    return None


def _fmt_hk_date(s: str) -> str | None:
    """dd/mm/yyyy -> yyyy-mm-dd。"""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(s or ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else (s or None)


_MONTHS = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
           "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
def _fmt_hk_updated(s: str) -> str | None:
    """'14 Jul 2026' / '14 July 2026' -> 'yyyy-mm-dd'。"""
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", str(s or ""), re.I)
    if not m:
        return s or None
    mon = _MONTHS.get(m.group(2)[:3].lower())
    if not mon:
        return s or None
    return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"


def map_app_record(rec: dict, board: str) -> Filing:
    has_phip = bool(rec.get("hasPhip"))
    status = "聆讯后资料集(PHIP)" if has_phip else "申请版本"

    docs = (rec.get("ls") or []) + (rec.get("ps") or [])
    phip_url = _doc_url(docs, ["聆訊後資料集", "聆讯后资料集", "Post Hearing"])
    ap_url = _doc_url(docs, ["申請版本", "申请版本", "Application Proof"])

    raw_name = (rec.get("a") or "").strip()
    name, markers = parse_hkex_markers(raw_name)

    now = utc_now_iso()
    return Filing(
        exchange="港交所",
        board=board,
        company_name=name,
        markers=markers,
        status=status,
        stage=normalize_stage("港交所", status),
        stock_code=str(rec.get("id")) if rec.get("id") is not None else None,
        prospectus_url=phip_url or ap_url,   # 最新可读披露文档(有PHIP用PHIP,否则用申请版本)
        phip_url=phip_url,
        page_updated=_fmt_hk_date(rec.get("d")),
        source_url="https://www1.hkexnews.hk/app/appindex.html",
        first_seen=now,
        last_seen=now,
    )
