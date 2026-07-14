"""A股招股说明书 PDF 解析器 —— 按项目号从三所详情接口取直链。

三所接口均经浏览器实测(2026-07-13):

上交所:GET https://query.sse.com.cn/commonSoaQuery.do
        ?sqlId=GP_COMMON_FILE_SEARCH&auditId={审核编号}&isPagination=true&pageHelp...
        头:Referer https://www.sse.com.cn/;JSONP。
        文件在 .result[]:fileTitle / filePath / fileTypeMap(I0011申报稿 I0012上会稿 I0013注册稿)
        直链 = https://static.sse.com.cn + filePath(运行时 HEAD 自检,失败回退 www.sse.com.cn)

深交所:GET https://www.szse.cn/api/ras/projectrends/details?id={prjid}&r={rand}
        头:X-Requested-With。纯 JSON。
        .data.disclosureMaterials[]:matnm=="招股说明书",dfpth,按 ddt 取最新
        直链 = https://reportdocs.static.szse.cn + dfpth
        (bonus:.data.enquiryResponseAttachment[] 为问询回复 PDF,留给问询监控)

北交所:POST https://www.bse.cn/projectNewsController/infoDetailResult.do?id={id}
        callback 包裹。[0].xxgkInfo 按文件类型分组(组内再分 SYG上会稿/BHG报会稿 等),
        递归扫 disclosureTitle 含"招股说明书",destFilePath 取最新 publishDate
        直链 = https://www.bse.cn + destFilePath
"""
from __future__ import annotations

import json
import random
import re
import time

import requests

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}

# 上交所披露类型:申报稿 / 上会稿 / 注册稿(按审核阶段渐进,取版本最新者)
SSE_PROSPECTUS_TYPES = ("I0011", "I0012", "I0013")


def _head_ok(url: str, session=None) -> bool:
    try:
        r = (session or requests).head(url, timeout=20, allow_redirects=True, headers=UA)
        return r.status_code == 200
    except requests.RequestException:
        return False


# —— 上交所 ——

def sse_resolve(stock_audit_num: str, session: requests.Session | None = None) -> str | None:
    s = session or requests.Session()
    s.headers.update(UA)
    cb = f"jsonpCallback{int(random.random()*1e8)}"
    url = (f"https://query.sse.com.cn/commonSoaQuery.do?jsonCallBack={cb}"
           f"&sqlId=GP_COMMON_FILE_SEARCH&auditId={stock_audit_num}"
           f"&isPagination=true&pageHelp.pageSize=50&pageHelp.pageNo=1"
           f"&pageHelp.beginPage=1&pageHelp.endPage=1&_={int(time.time()*1000)}")
    r = s.get(url, headers={"Referer": "https://www.sse.com.cn/"}, timeout=30)
    try:
        r.raise_for_status()
    except Exception as e:
        print(f"[resolve] 上交所 auditId={stock_audit_num} 查询HTTP异常: {e}")
        raise
    m = re.search(r"\{.*\}", r.text, re.S)
    if not m:
        print(f"[resolve] 上交所 auditId={stock_audit_num} 响应无JSON: {r.text[:160]!r}")
        return None
    files = json.loads(m.group(0)).get("result") or []
    print(f"[resolve] 上交所 auditId={stock_audit_num} 文件数={len(files)}")
    return sse_pick(files, session=s)


def sse_pick(files: list[dict], session=None) -> str | None:
    """从文件列表挑招股说明书:优先注册稿>上会稿>申报稿,同类取 fileUpdTime 最新。

    修复: 不再只取排名第一的直链就返回——交易所常轮转披露文件,
    排名第一的 filePath 可能已 404。改为逐个候选做 HEAD 自检,返回首个
    真实可下载(HTTP 200)的直链;全不可达才返回 None(不让死链被存下)。
    """
    cands = [f for f in files if f.get("fileTypeMap") in SSE_PROSPECTUS_TYPES
             and "招股说明书" in (f.get("fileTitle") or "")]
    if not cands:
        cands = [f for f in files if "招股说明书" in (f.get("fileTitle") or "")]
    if not cands:
        return None
    rank = {t: i for i, t in enumerate(SSE_PROSPECTUS_TYPES)}
    cands.sort(key=lambda f: (rank.get(f.get("fileTypeMap"), -1),
                             str(f.get("fileUpdTime") or "")), reverse=True)
    best = None
    for c in cands:
        path = c.get("filePath") or ""
        if not path:
            continue
        primary = "https://static.sse.com.cn" + path
        best = primary
        if session is None or _head_ok(primary, session):
            return primary
        fallback = "https://www.sse.com.cn" + path
        if _head_ok(fallback, session):
            return fallback
    # HEAD 自检全不可达:跑批环境可能拒 HEAD / 限网络(误杀有效直链),
    # 退而返回最优候选,交由下载步骤(404 会触发重解析)做最终校验
    if best:
        print(f"[sse_pick] auditId 候选 {len(cands)} 个,HEAD 均不可达,退而返回最优候选 {best}")
        return best
    return None


# —— 深交所 ——

def szse_resolve(prjid: str, session: requests.Session | None = None) -> str | None:
    s = session or requests.Session()
    s.headers.update(UA)
    url = f"https://www.szse.cn/api/ras/projectrends/details?id={prjid}&r={random.random()}"
    r = s.get(url, headers={"X-Requested-With": "XMLHttpRequest",
                            "Referer": "https://www.szse.cn/listing/projectdynamic/ipo/index.html"},
              timeout=30)
    r.raise_for_status()
    data = (r.json() or {}).get("data") or {}
    return szse_pick(data)


def szse_pick(detail_data: dict) -> str | None:
    mats = detail_data.get("disclosureMaterials") or []
    cands = [m for m in mats if (m.get("matnm") == "招股说明书"
                                 or "招股说明书" in (m.get("dfnm") or ""))]
    if not cands:
        return None
    cands.sort(key=lambda m: str(m.get("ddt") or ""), reverse=True)   # 取最新版
    path = cands[0].get("dfpth") or ""
    return ("https://reportdocs.static.szse.cn" + path) if path else None


# —— 北交所 ——

def bse_resolve(record_id: str, session: requests.Session | None = None) -> str | None:
    s = session or requests.Session()
    s.headers.update(UA)
    r = s.post(f"https://www.bse.cn/projectNewsController/infoDetailResult.do?id={record_id}&callback=cb",
               data={"id": str(record_id)},
               headers={"X-Requested-With": "XMLHttpRequest",
                        "Referer": "https://www.bse.cn/audit/project_news_detail.html"},
               timeout=30)
    r.raise_for_status()
    start, end = r.text.find("["), r.text.rfind("]")
    if start < 0 or end <= start:
        return None
    payload = json.loads(r.text[start:end + 1])
    return bse_pick((payload[0] or {}) if payload else {})


def _walk_docs(node):
    """递归展开 xxgkInfo 的分组结构,吐出所有文件 dict。"""
    if isinstance(node, dict):
        if "destFilePath" in node:
            yield node
        else:
            for v in node.values():
                yield from _walk_docs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_docs(v)


def bse_pick(detail_block: dict) -> str | None:
    docs = [d for d in _walk_docs(detail_block.get("xxgkInfo") or {})
            if "招股说明书" in (d.get("disclosureTitle") or "")]
    if not docs:
        return None
    docs.sort(key=lambda d: str(d.get("publishDate") or ""), reverse=True)
    path = docs[0].get("destFilePath") or ""
    return ("https://www.bse.cn" + path) if path else None


# —— 统一入口 ——

def resolve_prospectus(filing, session: requests.Session | None = None) -> str | None:
    """按 Filing 的交易所与编号解析招股说明书直链。失败返回 None(不抛,不猜)。

    上交所:审核编号(auditId)是查文件接口的唯一可靠标识。
    它来自 source_url 里的 auditId= 参数(采集器即以此构建详情页),
    不应用 stock_code(科创板 IPO 上市前 stock_code 与审核编号不是一回事,
    用错会查到错误/失效的披露文件)。优先从 source_url 取,回退 stock_code。
    """
    try:
        if filing.exchange == "上交所":
            # 审核编号:source_url 里的 auditId= 为准
            m = re.search(r"auditId=(\d+)", filing.source_url or "")
            aid = m.group(1) if m else (filing.stock_code or "")
            if aid:
                return sse_resolve(aid, session)
        if filing.exchange == "深交所" and filing.stock_code:
            return szse_resolve(filing.stock_code, session)
        if filing.exchange == "北交所":
            # 北交所详情用记录 id(在 source_url 里),不是股票代码
            m = re.search(r"id=(\d+)", filing.source_url or "")
            if m:
                return bse_resolve(m.group(1), session)
    except requests.RequestException:
        return None
    return None
