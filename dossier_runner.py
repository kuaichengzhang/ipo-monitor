"""档案批处理:对 ★可选题 且有招股书 PDF 的公司自动建档。

策略(Paodekuai 拍板):只给过会及以后的公司建档(一周几家,成本可忽略);
其余公司不自动跑。已建档且招股书未更新的不重复建。
"""
from __future__ import annotations

import os
import re
import traceback
from pathlib import Path

from extractor import load_pdf, cid_trap_ratio, Page
from dossier import generate_dossier
from stages import is_trigger


def _safe_name(s: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff()()·-]", "_", s)[:60]


def run_dossiers(filings, out_dir: Path, max_new: int = 5):
    """为触发公司建档。无 API key 时静默跳过(打印一次提示)。"""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[档案] 未配置 ANTHROPIC_API_KEY,跳过建档(监控/看板不受影响)")
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = [f for f in filings if is_trigger(f.stage) and f.prospectus_url]
    built = 0
    for f in targets:
        if built >= max_new:
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
            print(f"[档案] ✓ {f.company_name}(闸门拦截 "
                  f"{len(report.rejected_no_cite)+len(report.rejected_banned)+len(report.rejected_bad_cite)} 句)")
            built += 1
            pdf_path.unlink(missing_ok=True)
        except Exception:
            print(f"[档案] ✗ {f.company_name} 建档失败:")
            traceback.print_exc()
