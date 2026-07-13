"""上交所采集器(科创板 + 主板 发行上市审核项目动态)—— 已接通真实接口。

数据源接口(经浏览器 Network 实测确认):
  GET https://query.sse.com.cn/commonSoaQuery.do
  必要参数:sqlId=SH_XM_LB(审核项目列表)、issueMarketType=1,2(1=科创板,2=主板)
  必要请求头:Referer: https://www.sse.com.cn/  (缺则被 ExceptionInterceptor 拦截)
  返回:JSONP,记录在 .result,总数在 .pageHelp.total

字段(实测):
  stockAuditName 公司名(个别带"科创板IPO项目"等后缀,已清洗)
  currStatus     审核状态数字码(见 STATUS_CODE)
  issueMarketType 板块码(1=科创板,2=主板)
  intermediary   中介机构数组,i_intermediaryType==1 为保荐机构,取 i_intermediaryAbbrName
  auditApplyDate 受理日期(yyyymmddHHMMSS)
  updateDate     更新时间(yyyymmddHHMMSS)
  planIssueCapital 拟募资(亿元)
  stockAuditNum  审核编号
  commitiResult  上市委会议结果(通过/未通过,常为空)
"""
from __future__ import annotations

import json
import random
import re
import time

from collectors.base import BaseCollector
from models import Filing, utc_now_iso
from stages import normalize_stage, PASSED, TERMINATED

ENTRY_PAGE = "https://www.sse.com.cn/listing/renewal/ipo/"
QUERY_URL = "https://query.sse.com.cn/commonSoaQuery.do"
SQL_ID = "SH_XM_LB"
SSE_HEADERS = {"Referer": "https://www.sse.com.cn/"}
PAGE_SIZE = 500

# currStatus 数字码 -> 状态文字(经页面状态筛选器实测)
STATUS_CODE = {
    1: "已受理", 2: "已问询", 3: "上市委审议", 9: "上市委审议",
    4: "提交注册", 5: "注册结果", 7: "中止及财报更新", 8: "终止", 10: "补充审核",
}
BOARD_CODE = {1: "科创板", 2: "主板"}

_NAME_SUFFIX = re.compile(r"(科创板|主板)?IPO项目$")


def _build_url(page_no: int = 1) -> str:
    cb = f"jsonpCallback{int(random.random() * 1e8)}"
    ts = str(int(time.time() * 1000))
    return (
        f"{QUERY_URL}?jsonCallBack={cb}&sqlId={SQL_ID}"
        f"&issueMarketType=1,2&currStatus=&province=&csrcCode=&keyword="
        f"&auditApplyDateBegin=&auditApplyDateEnd="
        f"&order=updateDate|desc,stockAuditNum|desc"
        f"&isPagination=true&pageHelp.cacheSize=1"
        f"&pageHelp.beginPage={page_no}&pageHelp.endPage={page_no}"
        f"&pageHelp.pageSize={PAGE_SIZE}&pageHelp.pageNo={page_no}&_={ts}"
    )


def _clean_name(name: str) -> str:
    return _NAME_SUFFIX.sub("", (name or "").strip()).strip()


def _sponsor(intermediary) -> str | None:
    """从中介机构数组里取保荐机构(type==1)简称。"""
    if not isinstance(intermediary, list):
        return None
    for org in intermediary:
        if isinstance(org, dict) and org.get("i_intermediaryType") == 1:
            return org.get("i_intermediaryAbbrName") or org.get("i_intermediaryName")
    return None


def _fmt_date(s) -> str | None:
    """yyyymmddHHMMSS -> yyyy-mm-dd。"""
    s = str(s or "")
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s or None


def map_record(record: dict) -> Filing:
    code = record.get("currStatus")
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None
    raw_status = STATUS_CODE.get(code, f"状态码{code}")

    # 上市委审议阶段:若已有会议结果,细化为过会/终止
    committee = str(record.get("commitiResult") or "")
    stage = normalize_stage("上交所", raw_status)
    if raw_status == "上市委审议" and committee:
        if "通过" in committee and "未" not in committee and "不" not in committee:
            stage = PASSED
        elif "未通过" in committee or "不通过" in committee:
            stage = TERMINATED

    board = BOARD_CODE.get(record.get("issueMarketType"), "科创板")

    now = utc_now_iso()
    return Filing(
        exchange="上交所",
        board=board,
        company_name=_clean_name(record.get("stockAuditName")),
        status=raw_status,
        stage=stage,
        stock_code=str(record.get("stockAuditNum") or "") or None,
        sponsor=_sponsor(record.get("intermediary")),
        page_updated=_fmt_date(record.get("updateDate")),
        source_url=ENTRY_PAGE,
        first_seen=now,
        last_seen=now,
    )


def parse_query_response(text: str) -> list[Filing]:
    """剥 JSONP -> json -> .result -> list[Filing]。"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return []
    data = json.loads(m.group(0))
    records = data.get("result") or []
    return [map_record(r) for r in records]


def response_total(text: str) -> int:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return 0
    data = json.loads(m.group(0))
    ph = data.get("pageHelp") or {}
    try:
        return int(ph.get("total") or 0)
    except (TypeError, ValueError):
        return 0


class SSECollector(BaseCollector):
    name = "sse_renewal_ipo"

    def collect(self) -> list[Filing]:
        self.session.headers.update(SSE_HEADERS)
        out: list[Filing] = []
        page = 1
        while True:
            text = self.get(_build_url(page))
            batch = parse_query_response(text)
            out.extend(batch)
            if len(batch) < PAGE_SIZE or page > 20:
                break
            page += 1
        return out
