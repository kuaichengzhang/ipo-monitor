"""北交所采集器(发行上市审核项目动态)—— 已接通真实接口。

数据源接口(经浏览器实测确认,2026-07):
  POST https://www.bse.cn/projectNewsController/infoResult.do?callback=xx
  表单:page(0起)、shzt(状态筛选,空=全部)、sortfield=updateDate、sorttype=desc、keyword
  请求头:Content-Type: application/x-www-form-urlencoded + X-Requested-With
  返回:callback([{countsInfo:[...], listInfo:{content:[...], totalPages, totalElements}}])
  实测 871 个项目 / 44 页。

字段(实测):companyName | status(P码) | sponsorOrg 保荐机构全称 | stockCode |
  receiveDate/updateDate(Java Date 对象,取 .time 毫秒) | id

P 码状态字典(取自页面官方筛选器):
  P01 已受理 | P02 已问询 | P100 上市委审议 | P03 上市委会议通过 | P04 上市委会议未通过 |
  P05 上市委会议暂缓 | P06 提交注册 | P101 注册结果 | P07-1 注册 | P07-2 核准 |
  P08-1 不予注册 | P08-2 不予核准 | P09 中止 | P10 终止
  (数据中亦见裸 "P07",按前缀归入注册结果)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

from collectors.base import BaseCollector
from models import Filing, utc_now_iso
from stages import normalize_stage

ENTRY_PAGE = "https://www.bse.cn/audit/project_news.html"
# 每家公司的官方详情页(招股说明书等文件披露于此)—— 经公司公告原文引用验证
DETAIL_URL = "https://www.bse.cn/audit/project_news_detail.html?id={num}"
QUERY_URL = "https://www.bse.cn/projectNewsController/infoResult.do?callback=cb"

BSE_HEADERS = {
    "Referer": ENTRY_PAGE,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# P码 -> 状态文字(官方筛选器实测)
P_STATUS = {
    "P01": "已受理", "P02": "已问询", "P100": "上市委审议",
    "P03": "上市委会议通过", "P04": "上市委会议未通过", "P05": "上市委会议暂缓",
    "P06": "提交注册", "P101": "注册结果",
    "P07-1": "注册生效", "P07-2": "核准", "P07": "注册生效",
    "P08-1": "不予注册", "P08-2": "不予核准",
    "P09": "中止", "P10": "终止",
}

CST = timezone(timedelta(hours=8))


def status_text(pcode: str) -> str:
    pcode = str(pcode or "").strip()
    if pcode in P_STATUS:
        return P_STATUS[pcode]
    # 裸前缀容错(如 P07-x 变体)
    for k in sorted(P_STATUS, key=len, reverse=True):
        if pcode.startswith(k):
            return P_STATUS[k]
    return pcode or "未知"


def _fmt_java_date(v) -> str | None:
    """Java Date 对象 {time: 毫秒} 或字符串 -> 'yyyy-mm-dd'。"""
    if isinstance(v, dict) and "time" in v:
        try:
            return datetime.fromtimestamp(v["time"] / 1000, tz=CST).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return None
    s = str(v or "")
    return s[:10] if len(s) >= 10 else (s or None)


def unwrap_callback(text: str):
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    return json.loads(text[start:end + 1])


def map_record(record: dict) -> Filing:
    st = status_text(record.get("status"))
    now = utc_now_iso()
    return Filing(
        exchange="北交所",
        board="北交所",
        company_name=str(record.get("companyName") or "").strip(),
        status=st,
        stage=normalize_stage("北交所", st),
        stock_code=str(record.get("stockCode") or "") or None,
        sponsor=str(record.get("sponsorOrg") or "").strip() or None,
        page_updated=_fmt_java_date(record.get("updateDate")),
        source_url=DETAIL_URL.format(num=record.get("id")) if record.get("id") is not None else ENTRY_PAGE,
        first_seen=now,
        last_seen=now,
    )


def parse_response(payload) -> tuple[list[Filing], int]:
    """[0].listInfo.content -> 记录;[0].listInfo.totalPages -> 总页数。"""
    if not payload:
        return [], 0
    li = (payload[0] or {}).get("listInfo") or {}
    content = li.get("content") or []
    total_pages = int(li.get("totalPages") or 0)
    return [map_record(r) for r in content], total_pages


class BSECollector(BaseCollector):
    name = "bse_project_news"

    def collect(self) -> list[Filing]:
        import time as _time
        self.session.headers.update(BSE_HEADERS)

        # 预热：先访问入口页
        try:
            self.session.get(ENTRY_PAGE, timeout=15)
        except Exception:
            pass

        out: list[Filing] = []
        page = 0
        total = 1
        max_retries = 3
        while page < total and page < 100:
            payload = {"page": str(page), "shzt": "", "sortfield": "updateDate",
                       "sorttype": "desc", "keyword": ""}

            # 重试 + 退避
            resp = None
            for attempt in range(max_retries):
                try:
                    resp = self.session.post(QUERY_URL, data=payload, timeout=self.timeout)
                    resp.raise_for_status()
                    break
                except Exception:
                    if attempt < max_retries - 1:
                        wait = 3 * (attempt + 1)
                        print(f"  [bse] 第 {attempt+1} 次失败，{wait}s 后重试...")
                        _time.sleep(wait)
                    else:
                        raise

            filings, total = parse_response(unwrap_callback(resp.text))
            out.extend(filings)
            page += 1
        return out
