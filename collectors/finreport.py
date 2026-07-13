"""财报披露公告采集器。

数据源:
  1. 巨潮资讯网(CNINFO) —— 覆盖沪深北三所上市公司公告
     API: POST http://www.cninfo.com.cn/new/hisAnnouncement/query
     关键参数: tabName=fulltext (必须), category (年报/半年报/季报), searchkey (业绩预告/业绩快报)
     交易所区分: 按股票代码前缀 (6xxxxx=上交所, 0/3xxxxx=深交所, 8/4xxxxx=北交所)
     注意: column 参数不按交易所过滤,不能依赖;category 对业绩预告/业绩快报无效,改用 searchkey

  2. 港交所(HKEX) —— 上市公司公告标题搜索
     API: GET https://www1.hkexnews.hk/search/titleSearchServlet.do
     result 字段是 JSON 字符串,需要二次 json.loads
     按标题关键词过滤: Final Results / Interim Results / Profit Warning 等
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import requests

from collectors.base import BaseCollector, DEFAULT_HEADERS
from models import FinReport

CST = timezone(timedelta(hours=8))

CNINFO_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_HEADERS = {
    "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
    "Content-Type": "application/x-www-form-urlencoded",
    "X-Requested-With": "XMLHttpRequest",
}

# CNINFO 类别码 (有效的)
CNINFO_CATEGORIES = {
    "年报": "category_ndbg_szsh",
    "半年报": "category_bndbg_szsh",
    "一季报": "category_yjdbg_szsh",
    "三季报": "category_sjdbg_szsh",
}

# 业绩预告/业绩快报用 searchkey 搜
CNINFO_SEARCH_KEYS = ["业绩预告", "业绩快报"]

HKEX_SEARCH_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"

HKEX_FIN_KEYWORDS = [
    (["FINAL RESULTS", "ANNUAL RESULTS"], "Annual Results"),
    (["INTERIM RESULTS", "HALF-YEAR RESULTS", "HALF YEAR RESULTS"], "Interim Results"),
    (["QUARTERLY RESULTS", "FIRST QUARTER", "THIRD QUARTER"], "Quarterly Results"),
    (["PROFIT WARNING"], "Profit Warning"),
    (["PROFIT ALERT", "POSITIVE PROFIT"], "Profit Alert"),
]


def _exchange_by_code(code: str) -> str | None:
    """按股票代码前缀判断交易所。5位=港交所(跳过),6位按首位判断。"""
    code = str(code).strip()
    if len(code) == 5 and code.isdigit():
        return "港交所"
    if len(code) != 6 or not code.isdigit():
        return None
    first = code[0]
    if first == "6":
        return "上交所"
    if first in ("0", "3"):
        return "深交所"
    if first in ("8", "4"):
        return "北交所"
    return None


def _fmt_timestamp(ts) -> str:
    """毫秒时间戳 -> YYYY-MM-DD。"""
    try:
        if isinstance(ts, (int, float)) and ts > 0:
            return datetime.fromtimestamp(ts / 1000, tz=CST).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        pass
    return str(ts)[:10] if ts else ""


def _extract_period(title: str) -> str:
    """从标题中提取报告期，如 '2026年半年度' / '2025年年度' / '2026年第一季度'。"""
    # 2025年年度报告 / 2025年年度报告(更正后)
    m = re.search(r"(\d{4})\s*年\s*年度", title)
    if m:
        return f"{m.group(1)}年年度"
    # 2026年半年度 / 2026年上半年
    m = re.search(r"(\d{4})\s*年\s*半[年度]+", title)
    if m:
        return f"{m.group(1)}年半年度"
    m = re.search(r"(\d{4})\s*年\s*上半年", title)
    if m:
        return f"{m.group(1)}年半年度"
    # 第一/三季度
    m = re.search(r"(\d{4})\s*年\s*第?[一二三]季度", title)
    if m:
        return m.group(0)
    # 2026半年度 (无"年"字)
    m = re.search(r"(\d{4})\s*半年度", title)
    if m:
        return f"{m.group(1)}年半年度"
    return ""


def _clean_title(title: str) -> str:
    return re.sub(r"<[^>]+>", "", title).strip()


class CNINFOFinReportCollector(BaseCollector):
    """巨潮资讯网财报公告采集器 —— 覆盖沪深北三所。"""

    name = "cninfo_finreport"

    def __init__(self, timeout: int = 30, session: requests.Session | None = None,
                 days: int = 7):
        super().__init__(timeout, session)
        self.days = days
        # 先访问首页拿 cookie
        try:
            self.session.get("http://www.cninfo.com.cn/", timeout=10)
        except Exception:
            pass

    def _date_range(self) -> str:
        now = datetime.now(CST)
        frm = (now - timedelta(days=self.days)).strftime("%Y-%m-%d")
        to = now.strftime("%Y-%m-%d")
        return f"{frm}~{to}"

    def _query(self, data: dict) -> list[dict]:
        """查询 CNINFO API，返回原始记录列表（自动分页）。"""
        data.setdefault("tabName", "fulltext")
        data.setdefault("seDate", self._date_range())
        all_records = []
        page = 1
        while True:
            data["pageNum"] = str(page)
            data["pageSize"] = "50"
            try:
                r = self.session.post(CNINFO_URL, data=data, headers=CNINFO_HEADERS, timeout=self.timeout)
                r.raise_for_status()
                j = r.json()
            except Exception:
                break
            records = j.get("announcements") or []
            all_records.extend(records)
            total = j.get("totalAnnouncement", 0)
            if len(all_records) >= total or not records or page > 20:
                break
            page += 1
        return all_records

    def collect(self) -> list[FinReport]:
        results: list[FinReport] = []
        seen_uids: set[str] = set()

        # 1. 按类别查 (年报/半年报/季报)
        for cat_name, cat_code in CNINFO_CATEGORIES.items():
            records = self._query({"category": cat_code})
            for rec in records:
                fr = self._map_record(rec, cat_name)
                if fr and fr.uid not in seen_uids:
                    seen_uids.add(fr.uid)
                    results.append(fr)

        # 2. 按关键词搜 (业绩预告/业绩快报)
        for kw in CNINFO_SEARCH_KEYS:
            records = self._query({"searchkey": kw})
            for rec in records:
                title = _clean_title(rec.get("announcementTitle", ""))
                # 确认标题确实包含关键词
                if kw not in title:
                    continue
                fr = self._map_record(rec, kw)
                if fr and fr.uid not in seen_uids:
                    seen_uids.add(fr.uid)
                    results.append(fr)

        return results

    def _map_record(self, rec: dict, report_type: str) -> FinReport | None:
        code = str(rec.get("secCode", "")).strip()
        exchange = _exchange_by_code(code)
        if not exchange or exchange == "港交所":
            return None  # 港交由 HKEX 采集器处理
        title = _clean_title(rec.get("announcementTitle", ""))
        return FinReport(
            exchange=exchange,
            company_name=str(rec.get("secName", "")).strip(),
            stock_code=code,
            report_type=report_type,
            report_period=_extract_period(title),
            title=title,
            announcement_date=_fmt_timestamp(rec.get("announcementTime")),
            announcement_url=f"http://www.cninfo.com.cn{rec.get('adjunctUrl', '')}" if rec.get("adjunctUrl") else "",
            source="CNINFO",
        )


class HKEXFinReportCollector(BaseCollector):
    """港交所财报公告采集器 —— 标题搜索。"""

    name = "hkex_finreport"

    def __init__(self, timeout: int = 30, session: requests.Session | None = None,
                 days: int = 7):
        super().__init__(timeout, session)
        self.days = days

    def collect(self) -> list[FinReport]:
        results: list[FinReport] = []
        seen_uids: set[str] = set()
        now = datetime.now(CST)
        from_d = (now - timedelta(days=self.days)).strftime("%Y%m%d")
        to_d = now.strftime("%Y%m%d")

        for lang in ("EN", "ZH"):
            page = 1
            while True:
                params = {
                    "sortDir": "0", "sortBy": "DateTime", "category": "0",
                    "market": "SEHK", "stockId": "",
                    "fromDate": from_d, "toDate": to_d,
                    "title": "", "lang": lang,
                    "pageSize": "100", "pageNum": str(page),
                }
                try:
                    r = self.session.get(HKEX_SEARCH_URL, params=params, timeout=self.timeout)
                    r.raise_for_status()
                    data = r.json()
                except Exception:
                    break

                result_raw = data.get("result", "")
                if isinstance(result_raw, str):
                    try:
                        records = json.loads(result_raw)
                    except json.JSONDecodeError:
                        break
                else:
                    records = result_raw

                if not isinstance(records, list) or not records:
                    break

                for rec in records:
                    if not isinstance(rec, dict):
                        continue
                    title = _clean_title(rec.get("SHORT_TEXT", rec.get("LONG_TEXT", "")))
                    if not title:
                        continue
                    title_upper = title.upper()
                    for kws, label in HKEX_FIN_KEYWORDS:
                        if any(kw in title_upper for kw in kws):
                            code = str(rec.get("STOCK_CODE", "")).strip()
                            fr = FinReport(
                                exchange="港交所",
                                company_name=str(rec.get("STOCK_NAME", "")).strip(),
                                stock_code=code,
                                report_type=label,
                                report_period=_extract_period(title),
                                title=title,
                                announcement_date=str(rec.get("DATE_TIME", ""))[:10],
                                announcement_url=str(rec.get("FILE_LINK", "")),
                                source="HKEX",
                            )
                            if fr.uid not in seen_uids:
                                seen_uids.add(fr.uid)
                                results.append(fr)
                            break

                if len(records) < 100 or page > 10:
                    break
                page += 1

        return results
