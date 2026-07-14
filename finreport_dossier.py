"""财报公告拆解 —— 业绩预告/业绩快报的短 PDF 解析。

拆解 4 个维度（用户 2026-07-14 拍板: 1A + 1234 + 3A）:
1. 核心财务数据 (营收/净利润/同比/EPS)
2. 业绩方向+原因 (预增/预减/扭亏 + 变动原因摘要)
3. 行业与赛道 (所属行业/主营业务/竞争格局)
4. 风险提示 (风险因素/应收账款/存货异常)

成本: 业绩预告/快报 PDF 通常 1-5 页, DeepSeek 每条几分钱。
"""
from __future__ import annotations

import os
import re
import tempfile
import traceback
from pathlib import Path

import requests

from dossier import call_deepseek, md_to_html
from extractor import load_pdf, Page, normalize_text

PROMPT_TEMPLATE = """你是财务公告解析助手。基于以下公告文本，提取 4 个维度的信息。

铁律:
1. 文本中没有的数据写"未披露"，不许编造。
2. 数字必须原文照录，不做换算。
3. 简洁直白，不写废话。

公司: {company}
公告类型: {report_type}
公告标题: {title}
报告期: {period}

公告文本:
{text}

按以下格式输出 Markdown（标题原样保留）:

## 核心财务数据
- 营业收入: （数字 + 同比变动）
- 净利润: （数字 + 同比变动）
- 扣非净利润: （数字 + 同比变动）
- 每股收益: （数字）
（文本中没有的项写"未披露"）

## 业绩方向与原因
- 业绩方向: 预增/预减/扭亏/续亏/续盈/其他
- 变动幅度: （如有具体数字）
- 变动原因: （一段话摘要，100字以内）

## 行业与赛道
- 所属行业:
- 主营业务: （一句话）
- 竞争格局: （一句话，如有）

## 风险提示
- （逐条列出公告中提到的风险因素，没有则写"未提及"）
"""


# ===== 医疗专属财报拆解 prompt (5维度) =====
MEDICAL_PROMPT_TEMPLATE = """你是医药行业财务公告解析助手，专注于医疗健康公司的财报拆解。基于以下公告文本，提取 5 个维度的信息。

铁律:
1. 文本中没有的数据写"未披露"，不许编造。
2. 数字必须原文照录，不做换算。
3. 简洁直白，不写废话。
4. 重点关注研发管线相关数据，这是医疗公司的核心。

公司: {company}
公告类型: {report_type}
公告标题: {title}
报告期: {period}

公告文本:
{text}

按以下格式输出 Markdown（标题原样保留）:

## 研发费用与管线进展
- 研发费用: （数字 + 同比变动，如有）
- 研发费用率: （研发费用/营收比例，如可计算）
- 管线进展: （本期有无新IND/NDA/BLA申报、临床推进、产品上市等里程碑，逐条列出）
（文本中没有的项写"未披露"）

## 分产品/业务收入
- （分产品线/适应症/业务板块的收入明细，如公告中有披露）
- 核心产品收入: （主力产品各自的收入及变动）
（如公告未分产品披露，写"未分产品披露"）

## 现金储备与烧钱速度
- 货币资金: （期末账上现金及等价物）
- 经营现金流: （本期经营性现金流净额）
- 烧钱速度估算: （如可从研发费用+经营亏损估算季度消耗）
（文本中没有的项写"未披露"）

## 授权/合作交易
- license-in/out: （本期有无引进或对外授权交易）
- BD合作: （与药企/机构的商业合作）
（无则写"未提及"）

## 监管里程碑
- IND/NDA/BLA: （本期有无提交或获批的药品申请）
- 临床读出: （有无临床试验数据读出）
- 其他批件: （CDE/FDA/NMPA批件等）
（无则写"未提及"）
"""


def _safe_name(s: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff()()·-]", "_", s)[:60]


def _download_pdf(url: str, dest: str, session: requests.Session | None = None,
                  timeout: int = 60) -> bool:
    s = session or requests.Session()
    s.headers.setdefault("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
    # CNINFO 需要 Referer 才能下载 PDF
    if "cninfo.com.cn" in url:
        s.headers.setdefault("Referer", "https://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice")
    elif "hkexnews.hk" in url:
        s.headers.setdefault("Referer", "https://www1.hkexnews.hk/")
    try:
        r = s.get(url, timeout=timeout, stream=True, allow_redirects=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return True
    except Exception:
        return False


def parse_finreport(company: str, report_type: str, title: str, period: str,
                    pdf_url: str, llm=call_deepseek,
                    session: requests.Session | None = None,
                    is_medical: bool = False) -> str | None:
    """下载 PDF -> 提取文本 -> LLM 拆解 -> 返回 markdown。"""
    if not pdf_url:
        return None

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if not _download_pdf(pdf_url, tmp_path, session):
            return None

        pages = load_pdf(tmp_path, max_pages=10)
        if not pages:
            return None

        text_parts = []
        for p in pages:
            t = normalize_text(p.text or "").strip()
            if t:
                text_parts.append(f"[p.{p.number}] {t}")
        text = "\n\n".join(text_parts)

        if not text.strip():
            return None

        if len(text) > 50000:
            text = text[:50000] + "\n[... 文本过长，已截断]"

        template = MEDICAL_PROMPT_TEMPLATE if is_medical else PROMPT_TEMPLATE
        prompt = template.format(
            company=company, report_type=report_type,
            title=title, period=period or "未标注", text=text,
        )

        md = llm(prompt)
        return md
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def finreport_dossier_link_map(out_dir: Path) -> dict:
    """扫描已生成的财报拆解 html，返回 {uid: 相对路径}。"""
    m = {}
    if out_dir.exists():
        for p in sorted(out_dir.glob("*.html")):
            # 文件名格式: {uid}.html
            m[p.stem] = f"data/finreport_dossiers/{p.name}"
    return m


def run_finreport_dossiers(reports: list, out_dir: Path,
                           max_new: int = 15) -> dict:
    """批量拆解财报公告，返回 {uid: html相对路径}。"""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 已有的档案先加载
    dossier_map = finreport_dossier_link_map(out_dir)

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[财报拆解] 未配置 DEEPSEEK_API_KEY，跳过拆解")
        return dossier_map

    # 只拆业绩预告和业绩快报
    target_types = {"业绩预告", "业绩快报", "Profit Warning", "Profit Alert"}
    targets = [r for r in reports if r.report_type in target_types and r.announcement_url]

    print(f"[财报拆解] 待处理: {len(targets)} 篇 (上限 {max_new})")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Referer": "https://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
    })
    # 先访问 CNINFO 首页拿 cookie
    try:
        session.get("https://www.cninfo.com.cn/", timeout=10)
    except Exception:
        pass

    built = 0
    for r in targets:
        if built >= max_new:
            print(f"[财报拆解] 已达上限 {max_new}，剩余下次再拆")
            break

        # 用 uid 做文件名，避免同名公司冲突
        safe_uid = r.uid

        # 已存在的不重复拆
        if safe_uid in dossier_map:
            continue

        print(f"[财报拆解] {r.stock_code} {r.company_name} - {r.report_type} ...", end=" ")

        is_med = getattr(r, 'industry', '') == '医疗健康'
        if is_med:
            print(f"[医疗] ", end="")

        md = parse_finreport(
            company=r.company_name, report_type=r.report_type,
            title=r.title, period=r.report_period,
            pdf_url=r.announcement_url, session=session,
            is_medical=is_med,
        )

        if md:
            full_md = (f"# 【财报拆解】{r.company_name} ({r.stock_code})\n\n"
                       f"> {r.report_type} | {r.report_period or '未标注报告期'} | "
                       f"披露日期: {r.announcement_date} | {r.exchange}\n"
                       f"> 机器生成 · 仅供参考\n\n{md}")
            html = md_to_html(full_md, title=f"{r.company_name} - {r.report_type}")
            (out_dir / f"{safe_uid}.html").write_text(html, encoding="utf-8")
            dossier_map[safe_uid] = f"data/finreport_dossiers/{safe_uid}.html"
            print("OK")
            built += 1
        else:
            print("FAIL (PDF下载或解析失败)")

    print(f"[财报拆解] 完成: 本次新建 {built} 篇，累计 {len(dossier_map)} 篇")
    return dossier_map
