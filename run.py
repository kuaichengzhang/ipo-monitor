"""CLI 入口。

用法:
    python run.py            # 抓取 -> 更新状态 -> 打印今日新增/变化 -> 导出 data/filings.json

每周一到五用 cron 跑一次即可,例如:
    0 9 * * 1-5  cd /path/to/ipo_monitor && python run.py >> data/run.log 2>&1
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from collectors.hkex import HKEXNewListingInfoCollector, HKEXAppProofCollector
from collectors.sse import SSECollector
from collectors.szse import SZSECollector
from collectors.bse import BSECollector
from collectors.finreport import CNINFOFinReportCollector, HKEXFinReportCollector
from dashboard import generate_dashboard
from dossier_runner import run_dossiers, dossier_link_map
from finreport_dossier import run_finreport_dossiers
from industry import classify_industry
from stages import is_trigger
from state import StateStore

DATA_DIR = Path(__file__).parent / "data"

# 已接线的采集器。四所全上后,把 A 股三所的 Collector 加进这个列表即可。
COLLECTORS = [
    HKEXNewListingInfoCollector(),    # 港交所:招股/发行阶段(已接通)
    HKEXAppProofCollector(),          # 港交所:申请版本/PHIP,过会触发(已接通)
    SSECollector(),                   # 上交所科创板+主板(已接通)
    SZSECollector(),                  # 深交所创业板+主板:机制就绪,CATALOGID待确认(优雅跳过)
    BSECollector(),                   # 北交所:机制就绪,Controller待确认(优雅跳过)
]


def main() -> int:
    all_filings = []
    for c in COLLECTORS:
        try:
            got = c.collect()
            print(f"[{c.name}] 抓到 {len(got)} 条")
            all_filings.extend(got)
        except NotImplementedError as e:
            print(f"[{c.name}] 跳过(未接线):{e}")
        except Exception:
            print(f"[{c.name}] 出错:")
            traceback.print_exc()

    # ===== 行业标签 enrichment =====
    # 给每家公司打行业标签（医疗健康子行业 + 18A标记）
    med_count = 0
    for f in all_filings:
        ind, sind, is18a = classify_industry(f.company_name, f.markers)
        f.industry = ind
        f.sub_industry = sind
        f.is_18a = is18a
        if ind:
            med_count += 1
    print(f"[行业标签] 医疗健康公司: {med_count} 家 / 共 {len(all_filings)} 家")

    store = StateStore(DATA_DIR / "state.json")
    diff = store.diff_and_update(all_filings)
    store.save()

    (DATA_DIR).mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "filings.json").write_text(
        json.dumps([f.to_dict() for f in all_filings], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ★可选题建档(在看板之前,让看板能挂档案链接)
    # ★ 只对本次新增/变化的触发公司建档,不把全部历史公司传进去逐一查
    recent_filings = [f for f in diff["new"] + diff["changed"] if is_trigger(f.stage)]
    print(f"[建档] 本次新增/变化的触发公司: {len(recent_filings)} 家(全量 {len(all_filings)} 条)")
    dmap_raw = run_dossiers(recent_filings, DATA_DIR / "dossiers")
    # safe_name -> 还原到公司名匹配(看板按公司名查)
    from dossier_runner import _safe_name
    dossier_map = {}
    for f in all_filings:
        key = _safe_name(f.company_name)
        if key in dmap_raw:
            dossier_map[f.company_name] = dmap_raw[key]

    # ===== 财报披露 =====
    print("\n===== 财报披露扫描 =====")
    finreports = []
    for fc in [CNINFOFinReportCollector(days=7), HKEXFinReportCollector(days=7)]:
        try:
            got = fc.collect()
            print(f"[{fc.name}] 抓到 {len(got)} 条财报")
            finreports.extend(got)
        except Exception:
            print(f"[{fc.name}] 出错:")
            traceback.print_exc()

    # 财报也打行业标签
    fin_med_count = 0
    for r in finreports:
        ind, sind, is18a = classify_industry(r.company_name)
        r.industry = ind
        r.sub_industry = sind
        r.is_18a = is18a
        if ind:
            fin_med_count += 1
    print(f"[行业标签] 医疗健康财报: {fin_med_count} 条 / 共 {len(finreports)} 条")

    (DATA_DIR / "finreports.json").write_text(
        json.dumps([r.to_dict() for r in finreports], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[财报] 共 {len(finreports)} 条，已保存 finreports.json")

    # 拆解业绩预告 + 业绩快报
    # max_new=50: 首跑处理上周积压(~30篇)，日常只处理新增(淡季0-5，旺季20-40)
    # 已有的会自动跳过(按uid去重)，所以50是安全上限而非每轮定额
    finreport_dossier_map = run_finreport_dossiers(finreports, DATA_DIR / "finreport_dossiers", max_new=50)

    # 生成可读网页看板(dashboard.html 放项目根,方便 GitHub Pages 直接服务)
    new_uids = {f.uid for f in diff["new"]}
    changed_uids = {f.uid for f in diff["changed"]}
    dashboard_html = generate_dashboard(all_filings, new_uids, changed_uids,
                                        dossier_map=dossier_map,
                                        finreports=finreports,
                                        finreport_dossier_map=finreport_dossier_map)
    (Path(__file__).parent / "dashboard.html").write_text(dashboard_html, encoding="utf-8")
    (Path(__file__).parent / "index.html").write_text(dashboard_html, encoding="utf-8")

    print("\n===== 今日新增 =====")
    if not diff["new"]:
        print("(无)")
    for f in diff["new"]:
        mk = f" [{'/'.join(f.markers)}]" if f.markers else ""
        trig = "  ★可选题" if is_trigger(f.stage) else ""
        code = f.stock_code or "—"
        print(f"  + [{f.exchange}·{f.board}] {code}  {f.company_name}{mk} — {f.stage}({f.status}){trig}")
        if f.prospectus_url:
            print(f"      招股书: {f.prospectus_url}")

    print("\n===== 状态变化 =====")
    if not diff["changed"]:
        print("(无)")
    for f in diff["changed"]:
        print(f"  ~ {f.stock_code}  {f.company_name} — 现:{f.status}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
