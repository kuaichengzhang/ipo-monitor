"""档案批处理:对 ★可选题 且有招股书 PDF 的公司自动建档。

策略(Paodekuai 拍板):只给过会及以后的公司建档(一周几家,成本可忽略);
其余公司不自动跑。已建档且招股书未更新的不重复建。
"""
from __future__ import annotations

import os
import re
import traceback
from pathlib import Path

from collectors.resolve import resolve_prospectus
from extractor import load_pdf, cid_trap_ratio, Page
from dossier import generate_dossier, md_to_html
from stages import is_trigger


def _safe_name(s: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff()()·-]", "_", s)[:60]


def dossier_link_map(out_dir: Path) -> dict:
    """扫描已生成的档案 html,返回 {公司名: 相对路径}(看板据此挂"拆解档案"按钮)。"""
    m = {}
    if out_dir.exists():
        for p in sorted(out_dir.glob("*.html")):
            m[p.stem] = f"data/dossiers/{p.name}"
    return m


def run_dossiers(filings, out_dir: Path, max_new: int = 3) -> dict:
    """为触发公司建档。返回 {公司名: 档案html相对路径}。无 API key 时跳过建档但仍返回已有档案。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[档案] 未配置 DEEPSEEK_API_KEY,跳过建档(监控/看板不受影响)")
        return dossier_link_map(out_dir)
    # A股触发公司先解析招股书直链(港交所自带;解析失败则跳过该公司,不猜)
    import requests as _rq
    _sess = _rq.Session()
    for f in filings:
        if is_trigger(f.stage) and not f.prospectus_url:
            url = resolve_prospectus(f, _sess)
            if url:
                f.prospectus_url = url
    targets = [f for f in filings if is_trigger(f.stage) and f.prospectus_url]
    print(f"[档案] 符合条件的目标公司: {len(targets)} 家 (本次上限 {max_new} 篇)")
    built = 0
    for f in targets:
        if built >= max_new:
            print(f"[档案] 已达本次上限 {max_new} 篇,剩余 {len(targets) - built} 家下次再建")
            break
        path = out_dir / f"{_safe_name(f.company_name)}.md"
        if path.exists():
            continue
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
            doc, report = generate_dossier(f.company_name, meta, pages)
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
