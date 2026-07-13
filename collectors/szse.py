"""深交所采集器(创业板 + 主板 发行上市审核项目动态)—— 已接通真实接口。

数据源接口(经浏览器实测确认,2026-07):
  GET https://www.szse.cn/api/ras/projectrends/query
      ?bizType=1&pageIndex={0起}&pageSize=N&random={随机数}
  请求头:Referer(本站页面)+ X-Requested-With: XMLHttpRequest
  返回纯 JSON:{totalSize, totalPage, stageList, data:[...]}(实测在审 1461 个项目)
  注意:不是旧的 ShowReport/data 模式;stageList 即官方状态字典。

字段(实测):cmpnm 公司名 | prjst 状态文字 | stage 阶段码 | boardName 主板/创业板 |
  sprinsts 保荐机构简称 | updtdt 更新日期 | acptdt 受理日期 | prjid 项目ID

官方状态字典(取自接口 stageList):
  受理:已受理 | 问询:已问询 | 上市委会议:通过/未通过/暂缓审议/复审通过/复审未通过 |
  提交注册 | 注册结果:注册生效/不予注册/补充审核/终止注册 | 中止 |
  终止:审核不通过/撤回/未在规定时限内回复
"""
from __future__ import annotations

import json
import random

from collectors.base import BaseCollector
from models import Filing, utc_now_iso
from stages import normalize_stage

ENTRY_PAGE = "https://www.szse.cn/listing/projectdynamic/ipo/index.html"
QUERY_URL = "https://www.szse.cn/api/ras/projectrends/query"
PAGE_SIZE = 200

SZSE_HEADERS = {
    "Referer": ENTRY_PAGE,
    "X-Requested-With": "XMLHttpRequest",
}


def _fmt_date(s) -> str | None:
    """'2026-07-13 ...' / '2026-07-13' -> 'yyyy-mm-dd'。"""
    s = str(s or "")
    return s[:10] if len(s) >= 10 else (s or None)


def map_record(record: dict) -> Filing:
    company = str(record.get("cmpnm") or "").strip()
    raw_status = str(record.get("prjst") or "").strip()
    board = str(record.get("boardName") or "").strip() or "创业板"
    sponsor = str(record.get("sprinsts") or "").strip() or None

    now = utc_now_iso()
    return Filing(
        exchange="深交所",
        board=board,
        company_name=company,
        status=raw_status,
        stage=normalize_stage("深交所", raw_status),
        stock_code=str(record.get("prjid")) if record.get("prjid") is not None else None,
        sponsor=sponsor,
        page_updated=_fmt_date(record.get("updtdt")),
        source_url=ENTRY_PAGE,
        first_seen=now,
        last_seen=now,
    )


def parse_query_response(text: str) -> tuple[list[Filing], int]:
    """返回 (本页记录, totalSize)。"""
    data = json.loads(text)
    rows = data.get("data") or []
    total = int(data.get("totalSize") or 0)
    return [map_record(r) for r in rows], total


class SZSECollector(BaseCollector):
    name = "szse_ras_projectrends"

    def collect(self) -> list[Filing]:
        self.session.headers.update(SZSE_HEADERS)
        out: list[Filing] = []
        page = 0
        total = None
        while True:
            url = (f"{QUERY_URL}?bizType=1&pageIndex={page}"
                   f"&pageSize={PAGE_SIZE}&random={random.random()}")
            filings, total = parse_query_response(self.get(url))
            out.extend(filings)
            if not filings or len(out) >= total or page > 100:
                break
            page += 1
        return out
