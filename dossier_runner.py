"""档案批处理:对有招股书 PDF 的公司自动建档(申报受理~注册生效/招股)。

策略(Paodekuai 拍板):拆解范围比"★可选题"更宽——申报受理、已问询、上会
这三个早期阶段也建档案(只要有招股书 PDF)。已上市/中止/终止不建。
已建档且招股书未更新的不重复建。

★ 重要限流(Paodekuai 要求):resolve_prospectus 和建档都只看最近 7 天更新的公司,
不把上千家历史公司逐一查。首次运行也只处理一周内的。
"""
from __future__ import annotations

import os
import re
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from collectors.resolve import resolve_prospectus
from extractor import load_pdf, cid_trap_ratio, Page
from dossier import generate_dossier, md_to_html
from stages import is_dossier_eligible

CST = timezone(timedelta(hours=8))
RECENT_DAYS = 7


def _is_recent(page_updated: str | None, days: int = RECENT_DAYS) -> bool:
    """page_updated 是 'yyyy-mm-dd' 格式;7 天内算近期。无日期信息默认放过。"""
    if not page_updated:
        return True
    try:
        d = datetime.strptime(str(page_updated)[:10], "%Y-%m-%d").replace(tzinfo=CST)
        return (datetime.now(CST) - d).days <= days
    except (ValueError, TypeError):
        return True


def _safe_name(s: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff()()·-]", "_", s)[:60]


def _extract_dossier_pdf_url(md_path: Path) -> str:
    """从已有档案 .md 文件中提取招股书 PDF URL。"""
    try:
        content = md_path.read_text(encoding="utf-8")
        m = re.search(r"https?://\S+\.pdf", content)
        return m.group() if m else ""
    except Exception:
        return ""


def dossier_link_map(out_dir: Path) -> dict:
    """扫描已生成的档案 html,返回 {公司名: 相对路径}(看板据此挂"拆解档案"按钮)。"""
    m = {}
    if out_dir.exists():
        for p in sorted(out_dir.glob("*.html")):
            m[p.stem] = f"data/dossiers/{p.name}"
    return m


def run_dossiers(filings, out_dir: Path, max_new: int = 30,
                 changed_uids: set | None = None,
                 rebuild_all: bool = False) -> dict:
    """为触发公司建档。返回 {公司名: 档案html相对路径}。无 API key 时跳过建档但仍返回已有档案。

    changed_uids: 状态变化的公司 uid 集合。这些公司即使已有档案也会重建
    （招股书可能更新了，要看新的）。
    rebuild_all: 重建所有已有档案(闸门代码更新后用)。跳过 resolve,不限最近7天,
    只重建已存在的档案(不新建)。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[档案] 未配置 DEEPSEEK_API_KEY,跳过建档(监控/看板不受影响)")
        return dossier_link_map(out_dir)

    if rebuild_all:
        # 重建模式:遍历已有档案文件,从 meta 行提取 PDF URL
        # 不依赖 is_dossier_eligible(阶段可能已变化)和 filings.json(可能不完整)
        targets = []
        for md_path in sorted(out_dir.glob("*.md")):
            stem = md_path.stem  # 公司名
            content = md_path.read_text(encoding="utf-8")
            url_match = re.search(r"https?://\S+\.pdf", content)
            if not url_match:
                print(f"[档案] ⚠ {stem} 无法获取招股书URL,跳过")
                continue
            pdf_url = url_match.group()
            is_medical = "【医疗拆解档案】" in content
            # 尝试从 filings 中找到匹配的公司(获取 exchange/board/stage 等)
            filing = None
            for f in filings:
                if _safe_name(f.company_name) == stem:
                    filing = f
                    break
            if filing:
                if not filing.prospectus_url:
                    filing.prospectus_url = pdf_url
                # 保留旧档案的医疗标记(用户可能手动指定了医疗,但 classify_industry 按公司名没识别出来)
                if is_medical:
                    filing.industry = "医疗健康"
                targets.append(filing)
            else:
                # 不在 filings.json 中,用档案文件信息创建临时对象
                targets.append(SimpleNamespace(
                    company_name=stem, exchange="", board="", stage="",
                    prospectus_url=pdf_url, uid=stem,
                    industry="医疗健康" if is_medical else "",
                ))
        changed_uids = {f.uid for f in targets}
        max_new = len(targets) if targets else 1
        print(f"[档案] 重建模式:找到 {len(targets)} 个已有档案待重建")
    else:
        # 正常模式:resolve + _is_recent 过滤
        import requests as _rq
        _sess = _rq.Session()
        resolve_count = 0
        for f in filings:
            if is_dossier_eligible(f.stage) and not f.prospectus_url and _is_recent(f.page_updated):
                url = resolve_prospectus(f, _sess)
                if url:
                    f.prospectus_url = url
                    resolve_count += 1
        print(f"[档案] 本次 resolve_prospectus 查询 {resolve_count} 家(7天内的触发公司)")
        targets = [f for f in filings if is_dossier_eligible(f.stage) and f.prospectus_url and _is_recent(f.page_updated)]
        print(f"[档案] 符合条件的目标公司: {len(targets)} 家 (本次上限 {max_new} 篇)")

    built = 0
    for f in targets:
        if built >= max_new:
            if not rebuild_all:
                print(f"[档案] 已达本次上限 {max_new} 篇,剩余 {len(targets) - built} 家下次再建")
            break
        path = out_dir / f"{_safe_name(f.company_name)}.md"
        is_changed = changed_uids and f.uid in changed_uids
        # 检测招股书 URL 是否更新（即使 uid 没变，URL 变了也要重建）
        if path.exists() and not is_changed:
            old_url = _extract_dossier_pdf_url(path)
            if old_url and f.prospectus_url and old_url != f.prospectus_url:
                is_changed = True
                print(f"[档案] ↻ {f.company_name} 招股书URL已更新,重建档案")
        if path.exists() and not is_changed:
            continue  # 已有档案且无变化,跳过
        if is_changed and path.exists():
            print(f"[档案] ↻ {f.company_name} 重建档案")
        try:
            import requests as rq
            pdf_path = out_dir / "_tmp.pdf"
            r = rq.get(f.prospectus_url, timeout=120,
                       headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            pdf_path.write_bytes(r.content)
            pages = load_pdf(str(pdf_path))
            lang_note = ""
            if cid_trap_ratio(pages) < 0.02:
                lang_note = "(注意:该PDF中文不可提取或为英文版,页码以该版本为准)"
            meta = f"{f.exchange}·{f.board} · {f.stage} · {f.prospectus_url} {lang_note}"
            is_med = getattr(f, 'industry', '') == '医疗健康'
            if is_med:
                print(f"[医疗] ", end="")
            doc, report = generate_dossier(f.company_name, meta, pages, medical=is_med)
            path.write_text(doc, encoding="utf-8")
            path.with_suffix(".html").write_text(
                md_to_html(doc, title=f"拆解档案 · {f.company_name}"), encoding="utf-8")
            print(f"[档案] ✓ {f.company_name}(闸门拦截 "
                  f"{len(report.rejected_no_cite)+len(report.rejected_banned)+len(report.rejected_bad_cite)} 句)")
            built += 1
            pdf_path.unlink(missing_ok=True)
        except Exception:
            print(f"[档案] ✗ {f.company_name} 建档失败:")
            traceback.print_exc()
    return dossier_link_map(out_dir)
