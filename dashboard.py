"""看板 v2:可搜索、可筛选、分页加载的静态页(数据内嵌 JSON,原生 JS,无依赖)。

v2 修复(Paodekuai 首次部署反馈):
- 2554 张卡一页怼死 -> 分页(默认50张,点"加载更多")
- 没有交互 -> 搜索框 + 交易所页签 + 阶段筛选 + 只看★开关,默认按更新日期倒序
- 首次运行"今日新增=全库" -> 显示为"首次收录"
- 档案没有入口 -> 卡片上出"拆解档案"按钮(存在对应 html 时)
- A股无PDF链接 -> 卡片提供"审核页"链接(source_url),PDF二次查询待建
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone, timedelta

from stages import STAGE_ORDER, is_trigger

try:
    from pypinyin import lazy_pinyin, Style

    def _initials(text: str) -> str:
        return "".join(lazy_pinyin(text or "", style=Style.FIRST_LETTER)).lower()
except ImportError:      # 无 pypinyin 时优雅降级(仅失去拼音搜索)
    def _initials(text: str) -> str:
        return ""

CST = timezone(timedelta(hours=8))

STAGE_COLORS = {
    "申报受理": "#6b8cae", "已问询/回复": "#5b7db1", "上会/聆讯": "#4a6fa5",
    "过会/通过": "#1f6feb", "提交注册": "#1a5fd0", "注册生效/招股": "#0f4faf",
    "已上市": "#8a94a6", "中止": "#b08900", "终止/退回/未通过": "#a0522d", "未知": "#999",
}

FR_TYPE_COLORS = {
    "年报": "#1a73e8", "半年报": "#0097a7",
    "一季报": "#7b1fa2", "三季报": "#388e3c",
    "业绩预告": "#e8730c", "业绩快报": "#f9a825",
    "Profit Warning": "#dc3545", "Profit Alert": "#28a745",
    "Annual Results": "#6f42c1", "Interim Results": "#ad6ee0",
    "Quarterly Results": "#5c3dc4",
}


def _row(f, new_uids, changed_uids, dossier_map):
    return {
        "uid": f.uid,
        "ex": f.exchange, "bd": f.board, "code": f.stock_code or "",
        "name": f.company_name, "stage": f.stage, "status": f.status,
        "spon": f.sponsor or "", "date": f.page_updated or "",
        "content": f.content or "",
        "trig": is_trigger(f.stage),
        "new": f.uid in new_uids, "chg": f.uid in changed_uids,
        "pros": f.prospectus_url or "", "phip": f.phip_url or "",
        "src": f.source_url or "",
        "dossier": dossier_map.get(f.company_name, ""),
        "mk": "/".join(f.markers) if f.markers else "",
        "py": _initials(f.company_name),
        "pys": _initials(f.sponsor or ""),
        "ind": getattr(f, 'industry', '') or '',
        "sind": getattr(f, 'sub_industry', '') or '',
        "i18a": getattr(f, 'is_18a', False) or False,
    }


def _finreport_row(r, dossier_map):
    return {
        "ex": r.exchange, "code": r.stock_code or "",
        "name": r.company_name, "type": r.report_type,
        "period": r.report_period or "", "date": r.announcement_date or "",
        "url": r.announcement_url or "",
        "dossier": dossier_map.get(r.uid, ""),
        "title": r.title or "",
        "ind": getattr(r, 'industry', '') or '',
        "sind": getattr(r, 'sub_industry', '') or '',
        "i18a": getattr(r, 'is_18a', False) or False,
    }


def generate_dashboard(filings, new_uids=None, changed_uids=None,
                       updated_at=None, dossier_map=None,
                       finreports=None, finreport_dossier_map=None) -> str:
    new_uids = new_uids or set()
    changed_uids = changed_uids or set()
    dossier_map = dossier_map or {}
    finreports = finreports or []
    finreport_dossier_map = finreport_dossier_map or {}
    updated_at = updated_at or datetime.now(CST).strftime("%Y-%m-%d %H:%M")

    rows = [_row(f, new_uids, changed_uids, dossier_map) for f in filings]
    trigger_total = sum(1 for r in rows if r["trig"])
    new_total = sum(1 for r in rows if r["new"])
    first_run = new_total == len(rows) and len(rows) > 0
    new_label = f"首次收录 {new_total}" if first_run else f"今日新增 {new_total}"
    exchanges = sorted({r["ex"] for r in rows})
    dossier_total = sum(1 for r in rows if r["dossier"])

    data_json = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    stage_colors_json = json.dumps(STAGE_COLORS, ensure_ascii=False)
    stage_order_json = json.dumps(STAGE_ORDER, ensure_ascii=False)
    ex_tabs = "".join(f'<button class="tab" data-ex="{html.escape(e)}">{html.escape(e)}</button>' for e in exchanges)

    # 财报披露数据
    fr_rows = [_finreport_row(r, finreport_dossier_map) for r in finreports]
    fr_data_json = json.dumps(fr_rows, ensure_ascii=False).replace("</", "<\\/")
    fr_type_colors_json = json.dumps(FR_TYPE_COLORS, ensure_ascii=False)

    # 医疗健康频道数据
    med_filings = [r for r in rows if r.get("ind") == "医疗健康"]
    med_finreports = [r for r in fr_rows if r.get("ind") == "医疗健康"]
    med_total = len(med_filings) + len(med_finreports)
    med_18a_count = sum(1 for r in med_filings + med_finreports if r.get("i18a"))
    med_ipo_count = len(med_filings)
    med_filings_json = json.dumps(med_filings, ensure_ascii=False).replace("</", "<\\/")
    med_finreports_json = json.dumps(med_finreports, ensure_ascii=False).replace("</", "<\\/")
    sub_industries = sorted({r["sind"] for r in med_filings + med_finreports if r.get("sind")})
    med_exchanges = sorted({r["ex"] for r in med_filings + med_finreports if r.get("ex")})
    med_ex_tabs = "".join(
        f'<button class="tab" data-med-ex="{html.escape(e)}">{html.escape(e)}</button>'
        for e in med_exchanges
    )

    return r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IPO三棱镜 · 每日监控</title>
<style>
 :root { --blue:#1f6feb; --ink:#1a2233; --muted:#8a94a6; --line:#e6ebf2; --bg:#f6f8fb;
         --card:#fff; --card2:#eef2f8; --soft:#e8f0ff; --softline:#bcd3ff; --softink:#1a5fd0;
         --mark:#ffe9a8; --markink:#1a2233; --board-ink:#48566e; }
 @media (prefers-color-scheme: dark) {
   :root { --blue:#4d9bff; --ink:#e7ecf5; --muted:#8b96ab; --line:#2a3346; --bg:#0f1420;
           --card:#182031; --card2:#222c40; --soft:#1c2942; --softline:#2f4a7a;
           --softink:#8fbcff; --mark:#5a4a1a; --markink:#ffe9a8; --board-ink:#aab6cc; }
   header { background:linear-gradient(135deg,#12386f,#1f5fce) !important; }
   img, .med-stats { opacity:.95; }
 }
 * { box-sizing:border-box; } body { margin:0; font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif; background:var(--bg); color:var(--ink); line-height:1.5; }
 header { background:linear-gradient(135deg,#0f4faf,#1f6feb); color:#fff; padding:18px 16px; }
 header h1 { margin:0; font-size:19px; } header .sub { opacity:.9; font-size:13px; margin-top:4px; }
 header .stats { margin-top:8px; font-size:13px; } header .stats b { font-size:16px; }
 main { max-width:860px; margin:0 auto; padding:12px 12px 60px; }
 .controls { position:sticky; top:0; background:var(--bg); padding:10px 0; z-index:5; border-bottom:1px solid var(--line); }
 .search { width:100%; padding:9px 12px; border:1px solid var(--line); border-radius:8px; font-size:14px; background:var(--card); color:var(--ink); }
 .tabs { display:flex; gap:6px; margin-top:8px; flex-wrap:wrap; }
 .tab { border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:20px; padding:4px 12px; font-size:13px; cursor:pointer; }
 .tab.on { background:var(--blue); color:#fff; border-color:var(--blue); }
 .chips { display:flex; gap:6px; margin-top:6px; flex-wrap:wrap; align-items:center; }
 .chip { border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:20px; padding:2px 10px; font-size:12px; cursor:pointer; }
 .chip.on { background:var(--soft); border-color:var(--softline); color:var(--softink); }
 .count { color:var(--muted); font-size:12px; margin-left:auto; }
 .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 12px; margin-top:8px; }
 .card.trig { border-color:var(--softline); box-shadow:0 0 0 2px var(--soft) inset; }
 .l1 { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
 .name { font-weight:600; font-size:15px; } .code { color:var(--muted); font-size:12px; }
 .l2 { margin-top:6px; display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:12.5px; }
 .stage { color:#fff; padding:1px 8px; border-radius:20px; font-size:12px; }
 .board { background:var(--card2); color:var(--board-ink); padding:1px 7px; border-radius:20px; }
 .meta { color:var(--muted); } .l3 { margin-top:7px; font-size:12.5px; display:flex; gap:12px; flex-wrap:wrap; }
 .l3 a { color:var(--blue); text-decoration:none; } .l3 a:hover { text-decoration:underline; }
 .btn-dossier { background:var(--blue); color:#fff !important; padding:2px 10px; border-radius:6px; }
 .btn-watch { border:1px solid var(--line); background:transparent; color:var(--muted); border-radius:12px; padding:0 6px; font-size:13px; line-height:1.3; cursor:pointer; margin-left:auto; }
 .btn-watch.on { background:#fff3cd; border-color:#ffd43b; color:#b08900; }
 .badge { font-size:11px; padding:1px 7px; border-radius:20px; }
 .badge.star { background:#1f6feb; color:#fff; } .badge.new { background:#e8462d; color:#fff; } .badge.chg { background:#b08900; color:#fff; }
 .pager { display:flex; gap:6px; margin-top:16px; justify-content:center; align-items:center; flex-wrap:wrap; }
 .pager button { border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:8px; padding:6px 12px; font-size:13px; cursor:pointer; min-width:38px; }
 .pager button.cur { background:var(--blue); color:#fff; border-color:var(--blue); }
 .pager button:disabled { opacity:.4; cursor:default; }
 .pager .gap { color:var(--muted); }
 .pager select { border:1px solid var(--line); border-radius:8px; padding:6px 8px; font-size:13px; background:var(--card); color:var(--ink); }
 .pager .jump { width:56px; padding:6px 8px; border:1px solid var(--line); border-radius:8px; font-size:13px; background:var(--card); color:var(--ink); }
 mark { background:var(--mark); color:var(--markink); padding:0 1px; border-radius:2px; }
 .view-toggle { display:flex; gap:0; max-width:860px; margin:0 auto; padding:0 12px; }
 .vt-btn { flex:1; border:none; background:var(--card); border-bottom:3px solid transparent; padding:10px 16px; font-size:14px; cursor:pointer; color:var(--muted); }
 .vt-btn.on { color:var(--blue); border-bottom-color:var(--blue); font-weight:600; }
 .fr-card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 12px; margin-top:8px; }
 .fr-type { color:#fff; padding:1px 8px; border-radius:20px; font-size:12px; }
 .med-section-title { font-size:15px; color:var(--ink); margin:20px 0 4px; padding-bottom:6px; border-bottom:1px solid var(--line); }
 .med-stats { font-size:12px; color:var(--muted); margin-top:6px; }
 .badge.i18a { background:#e8730c; color:#fff; font-size:10px; padding:1px 6px; border-radius:20px; }
 .badge.sind { background:var(--soft); border:1px solid var(--softline); color:var(--softink); font-size:10px; padding:1px 6px; border-radius:20px; }
 footer { text-align:center; color:var(--muted); font-size:12px; padding:20px; }
 .toolbar { display:flex; gap:6px; align-items:center; margin-top:6px; flex-wrap:wrap; }
 .sort-sel { border:1px solid var(--line); border-radius:8px; padding:5px 8px; font-size:13px; background:var(--card); color:var(--ink); cursor:pointer; }
 .btn-export { border:1px solid var(--line); background:var(--card); border-radius:8px; padding:5px 12px; font-size:13px; cursor:pointer; color:var(--blue); }
 .btn-export:hover { background:var(--soft); }
 .btn-scan { border:1px solid var(--blue); background:var(--blue); color:#fff; border-radius:8px; padding:5px 12px; font-size:13px; cursor:pointer; text-decoration:none; display:inline-block; margin-left:8px; }
 .btn-scan:hover { filter:brightness(1.08); }
 .kbd-hint { font-size:11px; color:var(--muted); margin-left:auto; }
 .kbd { border:1px solid var(--line); border-radius:4px; padding:0 4px; font-size:11px; background:var(--card); }
 .stats-bar { display:flex; gap:2px; margin-top:8px; height:6px; border-radius:3px; overflow:hidden; }
 .stats-bar > div { flex:1; }
 .stats-legend { display:flex; gap:10px; margin-top:4px; font-size:11px; color:var(--muted); flex-wrap:wrap; }
 .stats-legend span { display:flex; align-items:center; gap:3px; }
 .stats-legend i { width:8px; height:8px; border-radius:2px; display:inline-block; }
 .stage-chips { display:flex; gap:4px; margin-top:6px; flex-wrap:wrap; }
 .stage-chip { border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:16px; padding:1px 8px; font-size:11px; cursor:pointer; white-space:nowrap; }
 .stage-chip.on { color:#fff; }
 .fr-search { width:100%; padding:8px 12px; border:1px solid var(--line); border-radius:8px; font-size:14px; margin-bottom:8px; background:var(--card); color:var(--ink); }
 .med-expand { color:var(--blue); text-decoration:none; font-size:13px; }
 @media(max-width:640px){
   header { padding:14px 12px; } header h1 { font-size:17px; } header .sub { font-size:12px; }
   header .stats { font-size:12px; } header .stats b { font-size:14px; }
   main { padding:8px 8px 50px; }
   .card { padding:9px 10px; } .name { font-size:14px; }
   .l2 { font-size:12px; gap:6px; } .l3 { font-size:12px; gap:8px; }
   .tab { padding:3px 10px; font-size:12px; }
   .chip { padding:2px 8px; font-size:11px; }
   .stage-chip { padding:1px 6px; font-size:10px; }
   .pager button { padding:5px 8px; font-size:12px; min-width:32px; }
   .vt-btn { padding:8px 10px; font-size:13px; }
   .kbd-hint { display:none; }
   .controls { padding:8px 0; }
   .sort-sel { font-size:12px; padding:4px 6px; }
   .btn-export { font-size:12px; padding:4px 8px; }
 }
</style></head><body>
<header>
  <h1>IPO三棱镜 · 每日监控</h1>
  <div class="sub">港交所 / 上交所 / 深交所 / 北交所 · 更新于 __UPDATED__</div>
  <div class="stats"><b>__TOTAL__</b> 家在管线 · <b>__TRIG__</b> 家 ★可选题 · __NEWLABEL__ · <b>__DOSSIERS__</b> 篇拆解 · 医疗 __MEDCOUNT__ 家 (18A __MED18A__)</div>
</header>
<div class="view-toggle">
  <button class="vt-btn on" data-view="ipo">IPO监控 (__TOTAL__)</button>
  <button class="vt-btn" data-view="fin">财报披露 (__FRTOTAL__)</button>
  <button class="vt-btn" data-view="med">医疗健康 (__MEDTOTAL__)</button>
  <button class="vt-btn" data-view="td">财报拆解</button>
</div>
<main>
  <div id="ipo-view">
  <div class="controls">
    <input class="search" id="q" placeholder="搜公司名 / 保荐机构 / 代码…">
    <div class="tabs"><button class="tab on" data-ex="">全部</button>__EXTABS__</div>
    <div class="chips">
      <span class="chip" data-f="trig">只看 ★可选题</span>
      <span class="chip" data-f="new">只看 新增/变化</span>
      <span class="chip" data-f="dossier">有拆解档案</span>
      <span class="chip" data-f="recent">近30天有动态</span>
      <span class="chip" data-f="yday">过去1个自然日发生</span>
      <span class="chip" data-f="today">今日更新</span>
      <span class="chip" data-f="med">只看 医疗健康</span>
      <span class="chip" data-f="watch">只看 关注</span>
      <span class="count" id="count"></span>
      <a class="btn-scan" href="https://github.com/kuaichengzhang/ipo-monitor/actions/workflows/daily.yml" target="_blank" rel="noopener" title="在新标签页打开 GitHub Actions，点 Run workflow 手动触发一次扫描（适合周末或非扫描时段补抓最新披露）">↻ 立即扫描</a>
    </div>
    <div class="stage-chips" id="stage-chips"></div>
    <div class="toolbar">
      <select class="sort-sel" id="sort">
        <option value="date">按日期 ↓</option>
        <option value="date-asc">按日期 ↑</option>
        <option value="name">按公司名 A-Z</option>
        <option value="stage">按阶段排序</option>
        <option value="ex">按交易所</option>
      </select>
      <button class="btn-export" id="export-csv">导出 CSV</button>
      <span class="kbd-hint">按 <span class="kbd">/</span> 搜索</span>
    </div>
    <div class="stats-bar" id="stats-bar"></div>
    <div class="stats-legend" id="stats-legend"></div>
  </div>
  <div id="list"></div>
  <div class="pager" id="pager"></div>
  </div>
  <div id="fin-view" style="display:none">
    <div class="controls">
      <input class="fr-search" id="fr-q" placeholder="搜公司名 / 代码 / 报告类型…">
      <div class="chips">
        <span class="chip on" data-fr-type="">全部</span>
        <span class="chip" data-fr-type="年报">年报</span>
        <span class="chip" data-fr-type="半年报">半年报</span>
        <span class="chip" data-fr-type="一季报">一季报</span>
        <span class="chip" data-fr-type="三季报">三季报</span>
        <span class="chip" data-fr-type="业绩预告">业绩预告</span>
        <span class="chip" data-fr-type="业绩快报">业绩快报</span>
        <span class="chip" data-fr-type="Annual Results">Annual Results</span>
        <span class="chip" data-fr-type="Interim Results">Interim Results</span>
        <span class="chip" data-fr-type="Quarterly Results">Quarterly Results</span>
        <span class="chip" data-fr-type="Profit Warning">Profit Warning</span>
        <span class="chip" data-fr-type="Profit Alert">Profit Alert</span>
        <span class="chip" data-fr-yday="1">过去1个自然日发生</span>
        <span class="chip" data-fr-today="1">今日更新</span>
        <span class="count" id="fr-count"></span>
        <a class="btn-scan" href="https://github.com/kuaichengzhang/ipo-monitor/actions/workflows/daily.yml" target="_blank" rel="noopener" title="在新标签页打开 GitHub Actions，点 Run workflow 手动触发一次扫描（适合周末或非扫描时段补抓最新披露）">↻ 立即扫描</a>
      </div>
    </div>
    <div id="fr-list"></div>
  </div>
  <div id="med-view" style="display:none">
    <div class="controls">
      <div class="tabs" id="med-ex-tabs"><button class="tab on" data-med-ex="">全部</button>__MEDEXTABS__</div>
      <div class="chips">
        <span class="chip on" data-med-recent="1">近90天有动态</span>
        <span class="chip" data-med-sind="">全部</span>__MEDCHIPS__
        <span class="chip" data-med-18a="1">只看 18A</span>
        <span class="chip on" data-med-show="all">全部</span>
        <span class="chip" data-med-show="ipo">只看 IPO</span>
        <span class="chip" data-med-show="fin">只看 财报</span>
        <span class="chip" data-med-yday="1">过去1个自然日发生</span>
        <span class="chip" data-med-today="1">今日更新</span>
        <span class="count" id="med-count"></span>
        <a class="btn-scan" href="https://github.com/kuaichengzhang/ipo-monitor/actions/workflows/daily.yml" target="_blank" rel="noopener" title="在新标签页打开 GitHub Actions，点 Run workflow 手动触发一次扫描（适合周末或非扫描时段补抓最新披露）">↻ 立即扫描</a>
      </div>
      <div class="med-stats" id="med-stats"></div>
    </div>
    <h3 class="med-section-title">IPO 动态 <span id="med-ipo-count" class="count"></span></h3>
    <div id="med-ipo-list"></div>
    <h3 class="med-section-title">财报拆解 <span id="med-fin-count" class="count"></span></h3>
    <div id="med-fin-list"></div>
  </div>
  <style>
   .td-card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-top:10px;}
   .td-h .name{font-weight:600;font-size:15px;} .td-tag{background:var(--soft);color:var(--softink);border:1px solid var(--softline);border-radius:20px;padding:1px 8px;font-size:11.5px;margin-left:4px;}
   .td-tag.trig{background:#e6fcf0;color:#0c8599;border-color:#99e9d2;}
   .td-badge{background:var(--card2);color:var(--board-ink);border-radius:20px;padding:1px 8px;font-size:11.5px;margin-left:4px;}
   .td-article-head{font-weight:600;margin-top:10px;font-size:14px;} .td-article{margin-top:6px;font-size:13px;line-height:1.7;}
   .td-metrics{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;} .td-metric{background:var(--card2);border-radius:8px;padding:6px 10px;min-width:120px;}
   .td-ml{font-size:11.5px;color:var(--muted);} .td-mv{font-size:14px;font-weight:600;} .td-mu{font-size:11px;color:var(--muted);font-weight:400;margin-left:2px;}
   .td-pg{font-size:11px;color:var(--muted);margin-left:6px;} .td-note{font-size:11.5px;color:var(--muted);margin-top:2px;}
   .td-score{margin-top:10px;font-size:12.5px;} .td-spine{margin-top:4px;font-size:12.5px;} .td-warn{display:inline-block;margin-top:6px;color:#b08900;background:#fff3cd;border:1px solid #ffd43b;border-radius:6px;padding:2px 8px;font-size:12px;}
   .td-sec{margin-top:10px;border-top:1px dashed var(--line);padding-top:8px;} .td-sect{font-size:12.5px;font-weight:600;color:var(--muted);margin-bottom:4px;}
   .td-line{font-size:12.5px;margin:3px 0;} .td-line.td-hit{color:#c92a2a;} .td-assets{margin:0;padding-left:18px;font-size:12.5px;} .td-assets li{margin:3px 0;}
   .td-links{margin-top:10px;display:flex;gap:10px;} .td-back,.td-backall{color:var(--blue);text-decoration:none;font-size:12.5px;} .td-backbar{margin-bottom:6px;}
   .td-link{background:#0c8599;color:#fff !important;padding:2px 10px;border-radius:6px;text-decoration:none;}
  </style>
  <div id="td-view" style="display:none">
    <div class="controls">
      <input class="search" id="td-q" placeholder="搜公司名 / 代码 / 报告类型…">
      <div class="chips">
        <span class="count" id="td-count"></span>
        <a class="btn-scan" href="https://github.com/kuaichengzhang/ipo-monitor/actions/workflows/daily.yml" target="_blank" rel="noopener" title="手动触发一次扫描">↻ 立即扫描</a>
      </div>
    </div>
    <div id="td-list"></div>
  </div>
</main>
<footer>★可选题 = 过会/PHIP及以后 · 档案为机器生成底稿 · 三棱镜成稿由作者本人撰写</footer>
<script>
const DATA = __DATA__;
const COLORS = __COLORS__;
const ORDER = __ORDER__;
// —— 状态(含 URL 同步,可把当前视图链接直接发给别人)——
function readState(){
  const p = new URLSearchParams(location.hash.slice(1));
  return { q:p.get('q')||'', ex:p.get('ex')||'',
           flags:Object.fromEntries((p.get('f')||'').split(',').filter(Boolean).map(k=>[k,true])),
           stage:p.get('st')||'',
           sort:p.get('sort')||'date',
           view:p.get('v')||'ipo',
           page:Math.max(1, parseInt(p.get('p')||'1')||1),
           size:[20,50,100].includes(parseInt(p.get('s')))?parseInt(p.get('s')):50,
           tdCode:p.get('tc')||'', tdDate:p.get('td')||'' };
}
let state = readState();
function writeState(){
  const p = new URLSearchParams();
  if(state.q) p.set('q', state.q);
  if(state.ex) p.set('ex', state.ex);
  const f = Object.keys(state.flags).filter(k=>state.flags[k]).join(',');
  if(f) p.set('f', f);
  if(state.stage) p.set('st', state.stage);
  if(state.sort!=='date') p.set('sort', state.sort);
  if(state.view!=='ipo') p.set('v', state.view);
  if(state.page>1) p.set('p', state.page);
  if(state.size!==50) p.set('s', state.size);
  if(state.tdCode) p.set('tc', state.tdCode);
  if(state.tdDate) p.set('td', state.tdDate);
  history.replaceState(null,'','#'+p.toString());
}
// —— 查询:多关键词 AND;每个词命中 公司名/保荐/代码/板块/阶段 或 拼音首字母 ——
function recentCut(){ const d=new Date(); d.setDate(d.getDate()-30); return d.toISOString().slice(0,10); }
function medRecentCut(){ const d=new Date(); d.setDate(d.getDate()-90); return d.toISOString().slice(0,10); }
// 北京时间(UTC+8)过去 1 个自然日 = 昨天整天(yyyy-mm-dd)
function bjDateStr(offset){
  const n = new Date();
  const bj = new Date(n.getTime() + 8*3600000); // 转北京时间
  bj.setUTCDate(bj.getUTCDate() + offset);
  const y = bj.getUTCFullYear();
  const m = String(bj.getUTCMonth()+1).padStart(2,'0');
  const d = String(bj.getUTCDate()).padStart(2,'0');
  return `${y}-${m}-${d}`;
}
function yday(){ return bjDateStr(-1); }
function today(){ return bjDateStr(0); }
function matches(r, terms){
  return terms.every(t => r.name.toLowerCase().includes(t) || r.spon.toLowerCase().includes(t)
    || r.code.includes(t) || r.bd.includes(t) || r.stage.includes(t) || r.status.includes(t)
    || (r.py && r.py.includes(t)) || (r.pys && r.pys.includes(t)));
}
function getWatchlist(){ try{ return new Set(JSON.parse(localStorage.getItem('ipo-watchlist')||'[]')); }catch(e){ return new Set(); } }
function setWatchlist(set){ localStorage.setItem('ipo-watchlist', JSON.stringify([...set])); }
function isWatched(r){ return getWatchlist().has(r.uid); }
function filtered(){
  const terms = state.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const cut = recentCut();
  let rows = DATA.filter(r => {
    if(state.ex && r.ex!==state.ex) return false;
    if(state.flags.trig && !r.trig) return false;
    if(state.flags.new && !(r.new||r.chg)) return false;
    if(state.flags.dossier && !r.dossier) return false;
    if(state.flags.recent && !(r.date && r.date>=cut)) return false;
    if(state.flags.med && r.ind!=='医疗健康') return false;
    if(state.flags.watch && !isWatched(r)) return false;
    if(state.flags.yday && !(r.date && r.date.slice(0,10)===yday())) return false;
    if(state.flags.today && !(r.date && r.date.slice(0,10)===today())) return false;
    if(state.stage && r.stage!==state.stage) return false;
    if(terms.length && !matches(r, terms)) return false;
    return true;
  });
  // 排序
  const s = state.sort || 'date';
  if(s==='date') rows.sort((a,b)=>(b.date||'').localeCompare(a.date||'') || ORDER.indexOf(a.stage)-ORDER.indexOf(b.stage));
  else if(s==='date-asc') rows.sort((a,b)=>(a.date||'').localeCompare(b.date||'') || ORDER.indexOf(a.stage)-ORDER.indexOf(b.stage));
  else if(s==='name') rows.sort((a,b)=>(a.name||'').localeCompare(b.name||''));
  else if(s==='stage') rows.sort((a,b)=>ORDER.indexOf(a.stage)-ORDER.indexOf(b.stage) || (b.date||'').localeCompare(a.date||''));
  else if(s==='ex') rows.sort((a,b)=>(a.ex||'').localeCompare(b.ex||'') || (b.date||'').localeCompare(a.date||''));
  return rows;
}
function esc(s){ s = (s===null||s===undefined)?'':s; return String(s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function hl(s, terms){
  let out = esc(s);
  for(const t of terms){ if(!t) continue;
    const re = new RegExp('('+t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','gi');
    out = out.replace(re,'<mark>$1</mark>');
  }
  return out;
}
function card(r, terms){
  const watched = isWatched(r);
  const badges = (r.trig?'<span class="badge star">★ 可选题</span>':'') + (r.new?'<span class="badge new">新</span>':(r.chg?'<span class="badge chg">状态更新</span>':''));
  const indTag = (r.ind==='医疗健康' && r.sind) ? '<span class="badge sind">'+esc(r.sind)+'</span>' : '';
  const i18aTag = r.i18a ? '<span class="badge i18a">18A</span>' : '';
  const links = [];
  if(r.dossier) links.push('<a class="btn-dossier" href="'+esc(r.dossier)+'">拆解档案</a>');
  if(r.phip) links.push('<a href="'+esc(r.phip)+'" target="_blank">聆讯后资料集</a>');
  if(r.pros && r.pros!==r.phip) links.push('<a href="'+esc(r.pros)+'" target="_blank">招股书</a>');
  if(r.src) links.push('<a href="'+esc(r.src)+'" target="_blank">'+(r.src.includes('detail')?'详情页·招股书披露':'交易所审核页')+'</a>');
  return '<div class="card '+(r.trig?'trig':'')+'">'
    +'<div class="l1"><span class="code">'+esc(r.code)+'</span><span class="name">'+hl(r.name,terms)+'</span>'+(r.mk?'<span class="board">'+esc(r.mk)+'</span>':'')+indTag+i18aTag+badges
    +'<button class="btn-watch '+(watched?'on':'')+'" data-uid="'+esc(r.uid)+'" title="关注">'+(watched?'★':'☆')+'</button></div>'
    +'<div class="l2"><span class="stage" style="background:'+(COLORS[r.stage]||'#5b7db1')+'">'+esc(r.stage)+'</span>'
    +'<span class="meta">'+esc(r.status)+'</span><span class="board">'+esc(r.bd)+'</span>'
    +(r.spon?'<span class="meta">保荐 '+hl(r.spon,terms)+'</span>':'')+(r.date?'<span class="meta">'+esc(r.date)+'</span>':'')+(r.content?'<span class="meta">更新内容: '+esc(r.content)+'</span>':'')+'</div>'
    +'<div class="l3">'+(links.join(' · ')||'<span class="meta">—</span>')+'</div></div>';
}
function pagerHtml(total){
  const pages = Math.max(1, Math.ceil(total/state.size));
  if(state.page>pages) state.page = pages;
  const cur = state.page;
  let nums = new Set([1,2,pages-1,pages,cur-1,cur,cur+1]);
  nums = [...nums].filter(n=>n>=1&&n<=pages).sort((a,b)=>a-b);
  let btns = '<button data-p="'+(cur-1)+'" '+(cur<=1?'disabled':'')+'>‹ 上一页</button>';
  let last = 0;
  for(const n of nums){
    if(n-last>1) btns += '<span class="gap">…</span>';
    btns += '<button data-p="'+n+'" class="'+(n===cur?'cur':'')+'">'+n+'</button>';
    last = n;
  }
  btns += '<button data-p="'+(cur+1)+'" '+(cur>=pages?'disabled':'')+'>下一页 ›</button>';
  btns += '<select id="psize"><option value="20"'+(state.size===20?' selected':'')+'>20/页</option><option value="50"'+(state.size===50?' selected':'')+'>50/页</option><option value="100"'+(state.size===100?' selected':'')+'>100/页</option></select>';
  btns += '<input class="jump" id="pjump" type="number" min="1" max="'+pages+'" placeholder="跳页" value="">';
  return btns;
}
function render(){
  const terms = state.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const rows = filtered();
  document.getElementById('count').textContent = rows.length + ' 家 · 第 ' + state.page + ' 页';
  const startI = (state.page-1)*state.size;
  document.getElementById('list').innerHTML = rows.slice(startI, startI+state.size).map(r=>card(r,terms)).join('') || '<div class="card"><span class="meta">没有匹配的公司</span></div>';
  document.getElementById('pager').innerHTML = pagerHtml(rows.length);
  document.querySelectorAll('#pager button[data-p]').forEach(b=>b.addEventListener('click', ()=>{
    state.page = parseInt(b.dataset.p); writeState(); render(); window.scrollTo({top:0});
  }));
  document.getElementById('psize').addEventListener('change', e=>{ state.size=parseInt(e.target.value); state.page=1; writeState(); render(); });
  document.getElementById('pjump').addEventListener('keydown', e=>{ if(e.key==='Enter'){ const v=parseInt(e.target.value); if(v){ state.page=v; writeState(); render(); window.scrollTo({top:0}); } } });
  // 关注按钮
  document.querySelectorAll('.btn-watch').forEach(b=>{
    b.addEventListener('click', ()=>{
      const set = getWatchlist();
      const uid = b.dataset.uid;
      if(set.has(uid)){ set.delete(uid); } else { set.add(uid); }
      setWatchlist(set);
      render();
    });
  });
  renderStageChips(rows.length);
  renderStatsBar(rows);
  writeState();
}
function renderStageChips(matchCount){
  const counts = {};
  DATA.forEach(r=>{ if(!state.ex || r.ex===state.ex) counts[r.stage]=(counts[r.stage]||0)+1; });
  const html = ORDER.filter(s=>counts[s]).map(s=>{
    const c = counts[s];
    const on = state.stage===s;
    return '<span class="stage-chip'+(on?' on':'')+'" data-st="'+esc(s)+'" style="'+(on?'background:'+(COLORS[s]||'#5b7db1')+';border-color:'+(COLORS[s]||'#5b7db1'):'')+'">'+esc(s)+' '+c+'</span>';
  }).join('');
  document.getElementById('stage-chips').innerHTML = html;
  document.querySelectorAll('.stage-chip[data-st]').forEach(c=>{
    c.addEventListener('click', ()=>{
      if(state.stage===c.dataset.st){ state.stage=''; }
      else { state.stage=c.dataset.st; }
      state.page=1; writeState(); render();
    });
  });
}
function renderStatsBar(rows){
  const exCounts = {};
  rows.forEach(r=>{ exCounts[r.ex]=(exCounts[r.ex]||0)+1; });
  const exColors = {'港交所':'#1f6feb','上交所':'#dc3545','深交所':'#28a745','北交所':'#fd7e14'};
  const total = rows.length;
  if(total===0){ document.getElementById('stats-bar').innerHTML=''; document.getElementById('stats-legend').innerHTML=''; return; }
  const bar = Object.entries(exCounts).sort((a,b)=>b[1]-a[1]).map(([ex,n])=>{
    const pct = (n/total*100).toFixed(0);
    return '<div style="width:'+pct+'%;background:'+(exColors[ex]||'#999')+'" title="'+esc(ex)+': '+n+'家 ('+pct+'%)"></div>';
  }).join('');
  document.getElementById('stats-bar').innerHTML = bar;
  const legend = Object.entries(exCounts).sort((a,b)=>b[1]-a[1]).map(([ex,n])=>{
    return '<span><i style="background:'+(exColors[ex]||'#999')+'"></i>'+esc(ex)+' '+n+'</span>';
  }).join('');
  document.getElementById('stats-legend').innerHTML = legend;
}
function exportCSV(){
  const rows = filtered();
  const headers = ['交易所','板块','代码','公司名','阶段','状态','保荐机构','更新日期','行业','子行业','18A','招股书','PHIP','审核页','拆解档案'];
  const lines = [headers.join(',')];
  rows.forEach(r=>{
    const vals = [r.ex,r.bd,r.code,r.name,r.stage,r.status,r.spon,r.date,r.content,r.ind||'',r.sind||'',r.i18a?'是':'',r.pros,r.phip,r.src,r.dossier];
    lines.push(vals.map(v=>{ v=v||''; v=String(v).replace(/"/g,'""'); return v.includes(',')||v.includes('"')||v.includes('\n')?'"'+v+'"':v; }).join(','));
  });
  const csv = '\ufeff'+lines.join('\n');
  const blob = new Blob([csv], {type:'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'ipo_monitor_'+new Date().toISOString().slice(0,10)+'.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}
let deb;
document.getElementById('q').value = state.q;
document.getElementById('q').addEventListener('input', e=>{
  clearTimeout(deb); deb = setTimeout(()=>{ state.q=e.target.value; state.page=1; render(); }, 200);
});
document.querySelectorAll('.tab').forEach(t=>{
  if(t.dataset.ex===state.ex){ document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on')); t.classList.add('on'); }
  t.addEventListener('click', ()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on')); t.classList.add('on');
    state.ex=t.dataset.ex; state.page=1; render();
  });
});
document.querySelectorAll('.chip[data-f]').forEach(c=>{
  if(state.flags[c.dataset.f]) c.classList.add('on');
  c.addEventListener('click', ()=>{
    c.classList.toggle('on'); state.flags[c.dataset.f]=c.classList.contains('on'); state.page=1; render();
  });
});
// —— 排序 ——
document.getElementById('sort').value = state.sort || 'date';
document.getElementById('sort').addEventListener('change', e=>{ state.sort=e.target.value; state.page=1; writeState(); render(); });
// —— 导出 CSV ——
document.getElementById('export-csv').addEventListener('click', exportCSV);
// —— 键盘快捷键: / 聚焦搜索 ——
document.addEventListener('keydown', e=>{
  if(e.key==='/' && document.activeElement.tagName!=='INPUT' && document.activeElement.tagName!=='SELECT'){
    e.preventDefault();
    const v = document.querySelector('.vt-btn.on').dataset.view;
    const target = v==='fin' ? document.getElementById('fr-q') : document.getElementById('q');
    if(target) target.focus();
  }
});
// —— 财报披露 ——
const FR_DATA = __FRDATA__;
const FR_COLORS = __FRCOLORS__;
let frFilter = '';
let frQuery = '';
let frYday = false;
let frToday = false;
function renderFR(){
  let rows = FR_DATA.slice();
  if(frFilter) rows = rows.filter(r=>r.type===frFilter);
  if(frQuery){
    const q = frQuery.toLowerCase();
    rows = rows.filter(r => r.name.toLowerCase().includes(q) || r.code.includes(q)
      || (r.type||'').toLowerCase().includes(q) || (r.title||'').toLowerCase().includes(q));
  }
  if(frYday) rows = rows.filter(r=>r.date && r.date.slice(0,10)===yday());
  if(frToday) rows = rows.filter(r=>r.date && r.date.slice(0,10)===today());
  rows.sort((a,b)=>(b.date||'').localeCompare(a.date||''));
  document.getElementById('fr-count').textContent = rows.length + ' 条';
  document.getElementById('fr-list').innerHTML = rows.map(r=>{
    const color = FR_COLORS[r.type] || '#5b7db1';
    const links = [];
    if(r.dossier) links.push('<a class="btn-dossier" href="'+esc(r.dossier)+'">拆解</a>');
    if(r.url) links.push('<a href="'+esc(r.url)+'" target="_blank">公告原文</a>');
    if(tdYes(r.code, r.date)) links.push('<a class="td-link" href="#" data-td-code="'+esc(r.code)+'" data-td-date="'+esc(r.date)+'">📊 拆解</a>');
    return '<div class="fr-card">'
      +'<div class="l1"><span class="code">'+esc(r.code)+'</span><span class="name">'+esc(r.name)+'</span><span class="fr-type" style="background:'+color+'">'+esc(r.type)+'</span></div>'
      +'<div class="l2"><span class="board">'+esc(r.ex)+'</span>'+(r.period?'<span class="meta">'+esc(r.period)+'</span>':'')+(r.date?'<span class="meta">'+esc(r.date)+'</span>':'')+'</div>'
      +'<div class="l3">'+(links.join(' · ')||'<span class="meta">—</span>')+'</div></div>';
  }).join('') || '<div class="card"><span class="meta">暂无财报数据</span></div>';
}
document.querySelectorAll('.chip[data-fr-type]').forEach(c=>{
  c.addEventListener('click', ()=>{
    document.querySelectorAll('.chip[data-fr-type]').forEach(x=>x.classList.remove('on'));
    c.classList.add('on'); frFilter = c.dataset.frType; renderFR();
  });
});
document.querySelector('.chip[data-fr-yday]').addEventListener('click', function(){
  this.classList.toggle('on'); frYday = this.classList.contains('on'); renderFR();
});
document.querySelector('.chip[data-fr-today]').addEventListener('click', function(){
  this.classList.toggle('on'); frToday = this.classList.contains('on'); renderFR();
});
let frDeb;
document.getElementById('fr-q').addEventListener('input', e=>{
  clearTimeout(frDeb); frDeb = setTimeout(()=>{ frQuery=e.target.value; renderFR(); }, 200);
});
// —— 医疗健康频道 ——
const MED_FILINGS = __MEDFILINGS__;
const MED_FINREPORTS = __MEDFINREPORTS__;
const FR_COLORS_MED = __FRCOLORS__;
const STAGE_COLORS_MED = __COLORS__;
let medSind = '', med18a = false, medEx = '', medRecent = true, medShow = 'all', medYday = false, medToday = false;
function renderMed(){
  const cut = medRecentCut();
  let ipoRows = MED_FILINGS.slice();
  let finRows = MED_FINREPORTS.slice();
  if(medEx){
    ipoRows = ipoRows.filter(r=>r.ex===medEx);
    finRows = finRows.filter(r=>r.ex===medEx);
  }
  if(medRecent){
    ipoRows = ipoRows.filter(r=>r.date && r.date>=cut);
    finRows = finRows.filter(r=>r.date && r.date>=cut);
  }
  if(medSind){
    ipoRows = ipoRows.filter(r=>r.sind===medSind);
    finRows = finRows.filter(r=>r.sind===medSind);
  }
  if(med18a){
    ipoRows = ipoRows.filter(r=>r.i18a);
    finRows = finRows.filter(r=>r.i18a);
  }
  if(medYday){
    ipoRows = ipoRows.filter(r=>r.date && r.date.slice(0,10)===yday());
    finRows = finRows.filter(r=>r.date && r.date.slice(0,10)===yday());
  }
  if(medToday){
    ipoRows = ipoRows.filter(r=>r.date && r.date.slice(0,10)===today());
    finRows = finRows.filter(r=>r.date && r.date.slice(0,10)===today());
  }
  ipoRows.sort((a,b)=>(b.date||'').localeCompare(a.date||''));
  finRows.sort((a,b)=>(b.date||'').localeCompare(a.date||''));
  const total = ipoRows.length + finRows.length;
  const i18aCnt = ipoRows.filter(r=>r.i18a).length + finRows.filter(r=>r.i18a).length;
  document.getElementById('med-count').textContent = total + ' 条';
  document.getElementById('med-stats').innerHTML = 'IPO动态 ' + ipoRows.length + ' · 财报 ' + finRows.length + (i18aCnt>0 ? ' · 18A公司 ' + i18aCnt : '');
  document.getElementById('med-ipo-count').textContent = ipoRows.length + ' 家';
  document.getElementById('med-fin-count').textContent = finRows.length + ' 条';
  const showIPO = medShow!=='fin';
  const showFin = medShow!=='ipo';
  const ipoListEl = document.getElementById('med-ipo-list');
  const ipoTitleEl = document.querySelector('.med-section-title:nth-of-type(1)');
  const finListEl = document.getElementById('med-fin-list');
  const finTitleEl = document.querySelector('.med-section-title:nth-of-type(2)');
  if(ipoTitleEl) ipoTitleEl.style.display = showIPO ? '' : 'none';
  if(showIPO){
    const ipoPageSize = medShow==='all' ? 5 : ipoRows.length;
    const ipoVisible = ipoRows.slice(0, ipoPageSize);
    ipoListEl.innerHTML = ipoVisible.map(r=>{
      const badges = (r.trig?'<span class="badge star">★</span>':'') + (r.i18a?'<span class="badge i18a">18A</span>':'') + (r.new?'<span class="badge new">新</span>':'');
      const sindTag = r.sind ? '<span class="badge sind">'+esc(r.sind)+'</span>' : '';
      const links = [];
      if(r.dossier) links.push('<a class="btn-dossier" href="'+esc(r.dossier)+'">拆解档案</a>');
      if(r.pros) links.push('<a href="'+esc(r.pros)+'" target="_blank">招股书</a>');
      if(r.src) links.push('<a href="'+esc(r.src)+'" target="_blank">审核页</a>');
      return '<div class="card '+(r.trig?'trig':'')+'">'
        +'<div class="l1"><span class="code">'+esc(r.code)+'</span><span class="name">'+esc(r.name)+'</span>'+sindTag+badges+'</div>'
        +'<div class="l2"><span class="stage" style="background:'+(STAGE_COLORS_MED[r.stage]||'#5b7db1')+'">'+esc(r.stage)+'</span>'
        +'<span class="meta">'+esc(r.status)+'</span><span class="board">'+esc(r.ex)+' · '+esc(r.bd)+'</span>'
        +(r.date?'<span class="meta">'+esc(r.date)+'</span>':'')+'</div>'
        +'<div class="l3">'+(links.join(' · ')||'<span class="meta">—</span>')+'</div></div>';
    }).join('') + (medShow==='all' && ipoRows.length>ipoPageSize ? '<div class="card" style="text-align:center;"><a href="#" class="med-expand" data-expand="ipo">展开全部 '+ipoRows.length+' 家 IPO</a></div>' : '')
    || '<div class="card"><span class="meta">暂无医疗健康 IPO 动态</span></div>';
  } else {
    ipoListEl.innerHTML = '';
  }
  if(finTitleEl) finTitleEl.style.display = showFin ? '' : 'none';
  if(showFin){
    finListEl.innerHTML = finRows.map(r=>{
      const color = FR_COLORS_MED[r.type] || '#5b7db1';
      const i18aTag = r.i18a ? '<span class="badge i18a">18A</span>' : '';
      const sindTag = r.sind ? '<span class="badge sind">'+esc(r.sind)+'</span>' : '';
      const links = [];
      if(r.dossier) links.push('<a class="btn-dossier" href="'+esc(r.dossier)+'">拆解</a>');
      if(r.url) links.push('<a href="'+esc(r.url)+'" target="_blank">公告原文</a>');
    if(tdYes(r.code, r.date)) links.push('<a class="td-link" href="#" data-td-code="'+esc(r.code)+'" data-td-date="'+esc(r.date)+'">📊 拆解</a>');
      return '<div class="fr-card">'
        +'<div class="l1"><span class="code">'+esc(r.code)+'</span><span class="name">'+esc(r.name)+'</span>'+sindTag+i18aTag+'<span class="fr-type" style="background:'+color+'">'+esc(r.type)+'</span></div>'
        +'<div class="l2"><span class="board">'+esc(r.ex)+'</span>'+(r.period?'<span class="meta">'+esc(r.period)+'</span>':'')+(r.date?'<span class="meta">'+esc(r.date)+'</span>':'')+'</div>'
        +'<div class="l3">'+(links.join(' · ')||'<span class="meta">—</span>')+'</div></div>';
    }).join('') || '<div class="card"><span class="meta">暂无医疗健康财报数据</span></div>';
  } else {
    finListEl.innerHTML = '';
  }
  // 展开全部按钮
  document.querySelectorAll('.med-expand').forEach(a=>{
    a.addEventListener('click', e=>{
      e.preventDefault();
      if(a.dataset.expand==='ipo'){ medShow='ipo'; }
      renderMed();
    });
  });
}
document.querySelectorAll('.chip[data-med-sind]').forEach(c=>{
  c.addEventListener('click', ()=>{
    document.querySelectorAll('.chip[data-med-sind]').forEach(x=>x.classList.remove('on'));
    c.classList.add('on'); medSind = c.dataset.medSind; renderMed();
  });
});
document.querySelector('.chip[data-med-18a]').addEventListener('click', function(){
  this.classList.toggle('on'); med18a = this.classList.contains('on'); renderMed();
});
document.querySelectorAll('.chip[data-med-show]').forEach(c=>{
  c.addEventListener('click', ()=>{
    document.querySelectorAll('.chip[data-med-show]').forEach(x=>x.classList.remove('on'));
    c.classList.add('on'); medShow = c.dataset.medShow || 'all'; renderMed();
  });
});
document.querySelectorAll('#med-ex-tabs .tab').forEach(t=>{
  t.addEventListener('click', ()=>{
    document.querySelectorAll('#med-ex-tabs .tab').forEach(x=>x.classList.remove('on'));
    t.classList.add('on'); medEx = t.dataset.medEx; renderMed();
  });
});
document.querySelector('.chip[data-med-recent]').addEventListener('click', function(){
  this.classList.toggle('on'); medRecent = this.classList.contains('on'); renderMed();
});
document.querySelector('.chip[data-med-yday]').addEventListener('click', function(){
  this.classList.toggle('on'); medYday = this.classList.contains('on'); renderMed();
});
document.querySelector('.chip[data-med-today]').addEventListener('click', function(){
  this.classList.toggle('on'); medToday = this.classList.contains('on'); renderMed();
});
// —— 财报拆解(teardown):运行时拉取 data/teardowns.json ——
let TD_CACHE = null;
let TD_MAP = {};
let tdQuery = '';
function tdYes(code, date){ return !!(code && date && TD_MAP[code+'|'+date]); }
function yoyColor(y){
  if(!y) return '';
  const s = String(y).trim();
  if(s[0]==='-') return '#2f9e44';
  if(s[0]==='+') return '#e03131';
  return '';
}
function fmtArticle(t){
  if(!t) return '';
  return esc(t).replace(/\n\n/g,'<br><br>').replace(/\n/g,'<br>').replace(/\*\*(.+?)\*\*/g,'<b>$1</b>');
}
function metricCell(m, label){
  if(!m) return '';
  const v = (m.value!==undefined && m.value!==null) ? m.value : '';
  const unit = m.unit||'';
  const yoy = m.yoy||'';
  const col = yoyColor(yoy);
  const yoyHtml = yoy ? ' <span style="color:'+col+'">'+esc(yoy)+'</span>' : '';
  const pg = m.page ? '<div class="td-pg">'+esc(m.page)+'</div>' : '';
  const note = m.note ? '<div class="td-note">'+esc(m.note)+'</div>' : '';
  return '<div class="td-metric"><div class="td-ml">'+esc(label)+'</div>'
    +'<div class="td-mv">'+esc(v)+'<span class="td-mu">'+esc(unit)+'</span>'+yoyHtml+'</div>'+pg+note+'</div>';
}
function renderTDCard(c){
  const h = c.header||{};
  const m = c.movements||{};
  const sc = c.scorecard||{};
  const src = c.source_url || (c._meta && c._meta.source_url) || (h.announcement_url) || "";
  const tags = (h.sector_tag||[]).map(function(t){return "<span class='td-tag'>"+esc(t)+"</span>";}).join("");
  const audit = h.audit_status ? "<span class='td-badge'>审计: "+esc(h.audit_status.value)+"</span>" : "";
  const rb = c.roundup_block||{};
  const ba = c.tier_basic_article||{};
  const articleText = rb.block_text || ba.article_text || ba.full_text || "";
  const articleHead = rb.headline_number || ba.headline_number || "";
  const metrics = [
    metricCell(m.revenue,"营收"),
    metricCell(m.net_profit_attributable,"归母净利润"),
    metricCell(m.net_profit_deducted,"扣非归母"),
    metricCell(m.gross_margin,"毛利率"),
    metricCell(m.net_margin,"净利率"),
    metricCell(m.operating_cash_flow,"经营现金流")
  ].join("");
  const trig = (sc.triggered||[]).map(function(t){return "<span class='td-tag trig'>"+esc(t)+"</span>";}).join("");
  const spine = sc.spine ? "<div class='td-spine'>主线："+esc(sc.spine)+"</div>" : "";
  const promote = sc.promote_to_standalone ? "<div class='td-warn'>建议独立深写："+(sc.promote_note||"")+"</div>" : "";
  const qd = c.quality_divergence||{};
  const qdHtml = Object.entries(qd).map(function(kv){
    const k=kv[0], v=kv[1];
    const val=(v&&(v.value||v.detail))||"";
    const pg=(v&&v.page)?" <span class='td-pg'>"+esc(v.page)+"</span>":"";
    const cls=(v&&v.hit)?"td-hit":"";
    return "<div class='td-line "+cls+"'><b>"+esc(k)+"</b>："+esc(val)+pg+"</div>";
  }).join("");
  const sg = c.signals||{};
  const sgHtml = Object.entries(sg).map(function(kv){
    const k=kv[0], v=kv[1];
    const hit=v&&v.hit;
    const val=(v&&(v.value||(v.detail&&v.detail.value)))||"";
    const pg=(v&&v.page)?" <span class='td-pg'>"+esc(v.page)+"</span>":"";
    const cls=hit?"td-hit":"";
    return "<div class='td-line "+cls+"'><b>"+esc(k)+"</b>："+(esc(val)||"(无)")+pg+"</div>";
  }).join("");
  let hc = "";
  if(c.healthcare_plugin){
    const hp=c.healthcare_plugin;
    const assets=(hp.pipeline&&hp.pipeline.core_assets||[]).map(function(a){
      return "<li><b>"+esc(a.name)+"</b> · "+(a.stage||"")+" · "+(a.indication||"")+" <span class='td-pg'>"+esc(a.page||"")+"</span>"+(a.period_change?"<div class='td-note'>"+esc(a.period_change)+"</div>":"");
    }).join("");
    const se=hp.selling_expense||{};
    const seHtml=se.selling_expense_ratio!==undefined?"<div class='td-line'>销售费用率：<b>"+esc(se.selling_expense_ratio)+(se.unit||"%")+"</b>"+(se.yoy?" <span style='color:"+yoyColor(se.yoy)+"'>"+esc(se.yoy)+"</span>":"")+(se.page?" <span class='td-pg'>"+esc(se.page)+"</span>":"")+"</div>":"";
    const vbp=(hp.vbp_reimbursement&&hp.vbp_reimbursement.revenue_impact)?"<div class='td-line'>集采医保："+esc(hp.vbp_reimbursement.revenue_impact)+(hp.vbp_reimbursement.price_cut!==undefined?"（降价"+esc(hp.vbp_reimbursement.price_cut)+"%）":"")+"</div>":"";
    const rnd=(hp.rnd&&hp.rnd.rnd_expense!==undefined)?"<div class='td-line'>研发：<b>"+esc(hp.rnd.rnd_expense)+(hp.rnd.unit||"亿元")+"</b>"+(hp.rnd.yoy?" <span style='color:"+yoyColor(hp.rnd.yoy)+"'>"+esc(hp.rnd.yoy)+"</span>":"")+(hp.rnd.page?" <span class='td-pg'>"+esc(hp.rnd.page)+"</span>":"")+"</div>":"";
    const cr=(hp.cash_runway&&hp.cash_runway.cash_reserve!==undefined)?"<div class='td-line'>现金储备：<b>"+esc(hp.cash_runway.cash_reserve)+(hp.cash_runway.unit||"亿元")+"</b></div>":"";
    hc="<div class='td-sec'><div class='td-sect'>医疗插件</div>"+(assets?"<ul class='td-assets'>"+assets+"</ul>":"")+seHtml+vbp+rnd+cr+"</div>";
  }
  const links=[];
  if(src) links.push("<a class='btn-dossier' href='"+esc(src)+"' target='_blank' rel='noopener'>查看原公告(PDF)</a>");
  links.push("<a href='#fin' class='td-back'>← 回财报披露</a>");
  return "<div class='td-card'>"
    +"<div class='td-h'><div class='l1'><span class='code'>"+esc(h.stock_code||h.ticker||"")+"</span><span class='name'>"+esc(h.company_name||"")+"</span>"+tags+audit+"</div>"
    +"<div class='l2'><span class='board'>"+esc(h.exchange||"")+"</span><span class='meta'>"+esc((h.report_type||"")+" "+(h.period||""))+"</span><span class='meta'>"+esc(h.disclosure_date||h.announcement_date||"")+"</span></div></div>"
    +(articleHead?"<div class='td-article-head'>"+esc(articleHead)+"</div>":"")
    +(articleText?"<div class='td-article'>"+fmtArticle(articleText)+"</div>":"")
    +(metrics?"<div class='td-metrics'>"+metrics+"</div>":"")
    +(sc.triggered_count!==undefined?"<div class='td-score'>触发看点 "+esc(sc.triggered_count)+" 个 "+trig+"</div>"+spine+promote:"")
    +(qdHtml?"<div class='td-sec'><div class='td-sect'>质量背离</div>"+qdHtml+"</div>":"")
    +(sgHtml?"<div class='td-sec'><div class='td-sect'>意外信号</div>"+sgHtml+"</div>":"")
    +hc
    +"<div class='td-links'>"+links.join(" ")+"</div>"
    +"</div>";
}
function showView(v){
  document.getElementById('ipo-view').style.display = v==='ipo' ? '' : 'none';
  document.getElementById('fin-view').style.display = v==='fin' ? '' : 'none';
  document.getElementById('med-view').style.display = v==='med' ? '' : 'none';
  document.getElementById('td-view').style.display = v==='td' ? '' : 'none';
}
async function loadTD(){
  if(TD_CACHE) return TD_CACHE;
  try{
    const r = await fetch('data/teardowns.json', {cache:'no-cache'});
    if(!r.ok) throw new Error('HTTP '+r.status);
    const arr = await r.json();
    TD_CACHE = Array.isArray(arr) ? arr : [];
  }catch(e){ TD_CACHE = TD_CACHE || []; console.warn('teardowns.json 加载失败', e); }
  TD_MAP = {};
  for(const c of TD_CACHE){
    const code = (c.header && (c.header.stock_code||c.header.ticker)) || '';
    const date = (c.header && (c.header.announcement_date||c.header.disclosure_date)) || '';
    if(code && date) TD_MAP[code+'|'+date] = c;
  }
  const tb = document.querySelector('.vt-btn[data-view="td"]');
  if(tb) tb.textContent = '财报拆解 ('+TD_CACHE.length+')';
  if(typeof renderFR==='function') renderFR();
  if(typeof renderMed==='function') renderMed();
  return TD_CACHE;
}
function openTeardown(code, date){
  document.querySelectorAll('.vt-btn').forEach(x=>x.classList.toggle('on', x.dataset.view==='td'));
  showView('td');
  state.view='td'; state.tdCode=code; state.tdDate=date; writeState();
  renderTD(); window.scrollTo({top:0});
}
async function renderTD(){
  const cards = await loadTD();
  let list = cards.slice();
  if(state.tdCode && state.tdDate){
    list = list.filter(c=>{
      const code=(c.header&&(c.header.stock_code||c.header.ticker))||'';
      const date=(c.header&&(c.header.announcement_date||c.header.disclosure_date))||'';
      return code===state.tdCode && date===state.tdDate;
    });
  } else if(tdQuery){
    const q=tdQuery.toLowerCase();
    list = list.filter(c=>{
      const h=c.header||{};
      return (h.company_name||'').toLowerCase().includes(q) || (h.stock_code||h.ticker||'').toLowerCase().includes(q)
        || (h.report_type||'').toLowerCase().includes(q) || (h.period||'').toLowerCase().includes(q);
    });
  }
  list.sort((a,b)=>((b.header&&b.header.disclosure_date)||'').localeCompare((a.header&&a.header.disclosure_date)||''));
  const el = document.getElementById('td-list');
  if(!list.length){
    el.innerHTML = '<div class="card"><span class="meta">暂无拆解卡片'+(state.tdCode?'（该公司/报告暂无）':'')+'</span></div>';
    return;
  }
  const back = (state.tdCode)?'<div class="td-backbar"><a href="#" class="td-backall">← 返回全部拆解</a></div>':'';
  el.innerHTML = back + list.map(renderTDCard).join('');
  const ba = el.querySelector('.td-backall');
  if(ba) ba.addEventListener('click', e=>{ e.preventDefault(); state.tdCode=''; state.tdDate=''; writeState(); renderTD(); });
}
let tdDeb;
const tdQEl = document.getElementById('td-q');
if(tdQEl) tdQEl.addEventListener('input', e=>{ clearTimeout(tdDeb); tdDeb=setTimeout(()=>{ tdQuery=e.target.value; renderTD(); }, 200); });
document.addEventListener('click', e=>{
  const a = e.target.closest('.td-link');
  if(a){ e.preventDefault(); openTeardown(a.dataset.tdCode, a.dataset.tdDate); }
});
document.querySelectorAll('.vt-btn').forEach(b=>{
  if(b.dataset.view===state.view) {
    document.querySelectorAll('.vt-btn').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');
    showView(state.view);
  }
  b.addEventListener('click', ()=>{
    document.querySelectorAll('.vt-btn').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');
    const v = b.dataset.view;
    state.view = v; state.tdCode=''; state.tdDate='';
    showView(v);
    writeState();
    if(v==='td') renderTD();
  });
});
renderFR();
renderMed();
render();
renderTD();
</script>
</body></html>""".replace("__UPDATED__", updated_at) \
   .replace("__TOTAL__", str(len(rows))).replace("__TRIG__", str(trigger_total)) \
   .replace("__NEWLABEL__", new_label).replace("__DOSSIERS__", str(dossier_total)) \
   .replace("__EXTABS__", ex_tabs).replace("__DATA__", data_json) \
   .replace("__COLORS__", stage_colors_json).replace("__ORDER__", stage_order_json) \
   .replace("__FRTOTAL__", str(len(fr_rows))).replace("__FRDATA__", fr_data_json) \
   .replace("__FRCOLORS__", fr_type_colors_json) \
   .replace("__MEDTOTAL__", str(med_total)) \
   .replace("__MEDCOUNT__", str(med_ipo_count)) \
   .replace("__MED18A__", str(med_18a_count)) \
   .replace("__MEDFILINGS__", med_filings_json) \
   .replace("__MEDFINREPORTS__", med_finreports_json) \
   .replace("__MEDCHIPS__", "".join(
       f'<span class="chip" data-med-sind="{html.escape(si)}">{html.escape(si)}</span>'
       for si in sub_industries
   )) \
   .replace("__MEDEXTABS__", med_ex_tabs)
