"""CLI 入口。

用法:
    python run.py                # 抓取 -> 更新状态 -> 打印今日新增/变化 -> 导出 data/filings.json
    python run.py --rebuild-all  # 同上,但重建所有已有拆解档案(闸门代码更新后用)

每周一到五用 cron 跑一次即可,例如:
    0 9 * * 1-5  cd /path/to/ipo_monitor && python run.py >> data/run.log 2>&1
"""
from __future__ import annotations

import argparse
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
from collectors.sw_industry import SWMedicalCache, _is_ashare
from models import Filing
from stages import is_trigger, is_dossier_eligible
from state import StateStore

DATA_DIR = Path(__file__).parent / "data"

# 已接线的采集器。四所全上后,把 A 股三所的 Collector 加进这个列表即可。
COLLECTORS = [
    HKEXNewListingInfoCollector(),    # 港交所:招股/发行阶段(已接通)
    HKEXAppProofCollector(),          # 港交所:申请版本/PHIP,过会触发(已接通)
    SSECollector(),                   # 上交所科创板+主板(已接通)
    SZSECollector(),                  # 深交所创业板+主板(已接通)
    BSECollector(),                   # 北交所:机制就绪,Controller待确认(优雅跳过)
]


# 采集器名前缀 -> 交易所名（兜底逻辑用）
_EXCHANGE_MAP = {
    "hkex": "港交所",
    "sse": "上交所",
    "szse": "深交所",
    "bse": "北交所",
}


def _collector_exchange(name: str) -> str:
    for prefix, ex in _EXCHANGE_MAP.items():
        if name.startswith(prefix):
            return ex
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="IPO 监控系统")
    parser.add_argument("--rebuild-all", action="store_true",
                        help="重建所有已有拆解档案(闸门代码更新后用)")
    args = parser.parse_args()

    # 加载上次 filings.json，按交易所分组（采集失败时兜底用）
    prev_by_exchange: dict[str, list[dict]] = {}
    prev_path = DATA_DIR / "filings.json"
    if prev_path.exists():
        try:
            prev_data = json.loads(prev_path.read_text(encoding="utf-8"))
            for d in prev_data:
                ex = d.get("exchange", "")
                if ex:
                    prev_by_exchange.setdefault(ex, []).append(d)
        except Exception:
            pass

    all_filings = []
    failed_exchanges: set[str] = set()

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
            ex = _collector_exchange(c.name)
            if ex:
                failed_exchanges.add(ex)

    # 旧数据兜底：采集失败的交易所，用上次缓存数据顶上
    if failed_exchanges:
        for ex in sorted(failed_exchanges):
            prev = prev_by_exchange.get(ex, [])
            if prev:
                print(f"[兜底] {ex} 采集失败，使用上次缓存: {len(prev)} 条")
                all_filings.extend(Filing.from_dict(d) for d in prev)

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

    # ★可选题建档(在看板之前,让看板能挂档案链接)
    # ★ 拆解范围:申报受理~注册生效/招股都拆(比选题触发更宽)
    # ★ resolve 阶段:传入所有可拆解公司(不只是 new/changed),
    #   让之前采集过但 prospectus_url=None 的公司也有机会被 resolve
    changed_uids = {f.uid for f in diff["changed"]}
    if args.rebuild_all:
        # 重建模式:传入所有 filings,重建已有档案
        recent_filings = [f for f in all_filings if is_dossier_eligible(f.stage)]
        print(f"[建档] 重建模式: {len(recent_filings)} 家可拆解公司(全量 {len(all_filings)} 条)")
    else:
        # 正常模式:传入所有可拆解公司(run_dossiers 内部用 _is_recent 过滤,
        # 只 resolve 最近7天 + 每次最多建 30 篇)
        recent_filings = [f for f in all_filings if is_dossier_eligible(f.stage)]
        new_changed_count = len([f for f in diff["new"] + diff["changed"] if is_dossier_eligible(f.stage)])
        print(f"[建档] 可拆解公司: {len(recent_filings)} 家(本次新增/变化 {new_changed_count} 家,全量 {len(all_filings)} 条)")
    dmap_raw = run_dossiers(recent_filings, DATA_DIR / "dossiers",
                            changed_uids=changed_uids,
                            rebuild_all=args.rebuild_all)

    # filings.json 在 resolve 之后写盘,确保 prospectus_url 被保存
    (DATA_DIR).mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "filings.json").write_text(
        json.dumps([f.to_dict() for f in all_filings], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
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

    # 财报行业标签: 按股票代码查申万医药生物(板块成分股, 按周缓存) —— 比 IPO 继承更准
    #   (已上市公司财报 与 未上市公司 IPO 申报 数据集几乎不重叠, 继承方案无效)
    #   A 股(6 位, 沪深): 命中申万医药生物成分 -> 医疗健康 + 申万二级子行业
    #   未命中(板块权威): 非医疗, 不标记
    #   北交所 / 港交所 / 代码缺失: 申万不覆盖, 走公司名关键词兜底
    #   若板块映射为空(东方财富限流拉取失败): 整体回退关键词兜底
    sw = SWMedicalCache(DATA_DIR / "sw_medical.json")
    sw_available = sw.available()
    fin_med_count = 0
    fin_sw_medical = 0      # 申万命中且为医疗
    fin_sw_nonmed = 0       # 申万权威排除(非医药生物 A 股)
    fin_fallback = 0         # 关键词兜底(港/北交所 / 映射不可用)
    for r in finreports:
        code = (r.stock_code or "").strip()
        if _is_ashare(code):
            if sw_available and sw.is_medical(code):
                r.industry = "医疗健康"
                r.sub_industry = sw.get_sub(code)
                fin_sw_medical += 1
            elif sw_available:
                # 板块权威: A 股但不在医药生物名单 -> 非医疗
                r.industry = ""
                r.sub_industry = ""
                fin_sw_nonmed += 1
            else:
                # 映射不可用(拉取失败) -> 关键词兜底
                ind, sind, is18a = classify_industry(r.company_name)
                r.industry, r.sub_industry, r.is_18a = ind, sind, is18a
                fin_fallback += 1
        else:
            # 北交所 / 港交所(5 位) / 代码缺失 -> 关键词兜底
            ind, sind, is18a = classify_industry(r.company_name)
            r.industry, r.sub_industry, r.is_18a = ind, sind, is18a
            fin_fallback += 1
        if r.industry:
            fin_med_count += 1
    sw.save()
    print(f"[行业标签] 医疗健康财报: {fin_med_count} 条 / 共 {len(finreports)} 条 "
          f"(申万医疗 {fin_sw_medical}, 申万非医疗 {fin_sw_nonmed}, 关键词兜底 {fin_fallback}; "
          f"申万成分股映射 {'可用' if sw_available else '不可用(已回退关键词)'}, "
          f"共 {sw.total()} 只(静态底表 {len(sw._static)} + 增量 {len(sw._extra)})")

    (DATA_DIR / "finreports.json").write_text(
        json.dumps([r.to_dict() for r in finreports], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[财报] 共 {len(finreports)} 条，已保存 finreports.json")

    # 拆解所有类型财报(年报/半年报/季报/业绩预告/业绩快报等)
    # max_new=50: 首跑处理上周积压(~30篇)，日常只处理新增(淡季0-5，旺季20-40)
    # 已有的会自动跳过(按uid去重)，所以50是安全上限而非每轮定额
    finreport_dossier_map = run_finreport_dossiers(finreports, DATA_DIR / "finreport_dossiers", max_new=50)

    # 生成可读网页看板(dashboard.html 放项目根,方便 GitHub Pages 直接服务)
    new_uids = {f.uid for f in diff["new"]}
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
