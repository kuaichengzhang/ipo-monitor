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
from dashboard import generate_dashboard
from dossier_runner import run_dossiers
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

    store = StateStore(DATA_DIR / "state.json")
    diff = store.diff_and_update(all_filings)
    store.save()

    (DATA_DIR).mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "filings.json").write_text(
        json.dumps([f.to_dict() for f in all_filings], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 生成可读网页看板(dashboard.html 放项目根,方便 GitHub Pages 直接服务)
    new_uids = {f.uid for f in diff["new"]}
    changed_uids = {f.uid for f in diff["changed"]}
    dashboard_html = generate_dashboard(all_filings, new_uids, changed_uids)
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

    # ★可选题自动建档(需 ANTHROPIC_API_KEY;未配置则跳过并提示)
    run_dossiers(all_filings, DATA_DIR / "dossiers")

    print("\n===== 状态变化 =====")
    if not diff["changed"]:
        print("(无)")
    for f in diff["changed"]:
        print(f"  ~ {f.stock_code}  {f.company_name} — 现:{f.status}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
