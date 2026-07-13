"""把监控结果渲染成一个网页(dashboard.html)。

无第三方依赖,纯字符串拼 HTML。蓝色系、手机友好。
按交易所分组,组内按阶段排序,过会及以后(触发)高亮 ★可选题,今日新增打"新"标。
"""
from __future__ import annotations

import html
from datetime import datetime, timezone, timedelta

from models import Filing
from stages import STAGE_ORDER, is_trigger

CST = timezone(timedelta(hours=8))

_STAGE_COLOR = {
    "申报受理": "#6b8cae", "已问询/回复": "#5b7db1", "上会/聆讯": "#4a6fa5",
    "过会/通过": "#1f6feb", "提交注册": "#1a5fd0", "注册生效/招股": "#0f4faf",
    "已上市": "#8a94a6", "中止": "#b08900", "终止/退回/未通过": "#a0522d", "未知": "#999",
}


def _esc(s) -> str:
    return html.escape(str(s)) if s else ""


def _doc_links(f: Filing) -> str:
    links = []
    if f.phip_url:
        links.append(f'<a href="{_esc(f.phip_url)}" target="_blank">聆讯后资料集</a>')
    if f.prospectus_url and f.prospectus_url != f.phip_url:
        links.append(f'<a href="{_esc(f.prospectus_url)}" target="_blank">招股书</a>')
    if f.announcement_url:
        links.append(f'<a href="{_esc(f.announcement_url)}" target="_blank">公告</a>')
    return " · ".join(links) or '<span class="muted">—</span>'


def _card(f: Filing, is_new: bool, is_changed: bool) -> str:
    trig = is_trigger(f.stage)
    color = _STAGE_COLOR.get(f.stage, "#5b7db1")
    badges = ""
    if trig:
        badges += '<span class="badge star">★ 可选题</span>'
    if is_new:
        badges += '<span class="badge new">新</span>'
    elif is_changed:
        badges += '<span class="badge chg">状态更新</span>'
    spon = f'<span class="meta">保荐 {_esc(f.sponsor)}</span>' if f.sponsor else ""
    date = f'<span class="meta">{_esc(f.page_updated)}</span>' if f.page_updated else ""
    code = f'<span class="code">{_esc(f.stock_code)}</span>' if f.stock_code else ""
    return f"""
    <div class="card {'trig' if trig else ''}">
      <div class="line1">{code}<span class="name">{_esc(f.company_name)}</span>{badges}</div>
      <div class="line2">
        <span class="stage" style="background:{color}">{_esc(f.stage)}</span>
        <span class="muted">{_esc(f.status)}</span>
        <span class="board">{_esc(f.board)}</span>
        {spon}{date}
      </div>
      <div class="line3">{_doc_links(f)}</div>
    </div>"""


def generate_dashboard(filings, new_uids=None, changed_uids=None,
                       updated_at: str | None = None) -> str:
    new_uids = new_uids or set()
    changed_uids = changed_uids or set()
    updated_at = updated_at or datetime.now(CST).strftime("%Y-%m-%d %H:%M")

    # 分组:交易所 -> 组内按阶段排序,触发的排前
    by_ex: dict[str, list[Filing]] = {}
    for f in filings:
        by_ex.setdefault(f.exchange, []).append(f)

    def sort_key(f: Filing):
        return (0 if is_trigger(f.stage) else 1, STAGE_ORDER.index(f.stage) if f.stage in STAGE_ORDER else 99)

    trigger_total = sum(1 for f in filings if is_trigger(f.stage))
    new_total = sum(1 for f in filings if f.uid in new_uids)

    sections = []
    for ex in sorted(by_ex.keys()):
        cards = "".join(
            _card(f, f.uid in new_uids, f.uid in changed_uids)
            for f in sorted(by_ex[ex], key=sort_key)
        )
        sections.append(f'<h2>{_esc(ex)} <span class="cnt">{len(by_ex[ex])}</span></h2>{cards}')

    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IPO三棱镜 · 每日监控</title>
<style>
 :root {{ --blue:#1f6feb; --ink:#1a2233; --muted:#8a94a6; --line:#e6ebf2; --bg:#f6f8fb; }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
        background:var(--bg); color:var(--ink); line-height:1.5; }}
 header {{ background:linear-gradient(135deg,#0f4faf,#1f6feb); color:#fff; padding:20px 16px; }}
 header h1 {{ margin:0; font-size:19px; }}
 header .sub {{ opacity:.9; font-size:13px; margin-top:4px; }}
 header .stats {{ margin-top:10px; font-size:13px; }}
 header .stats b {{ font-size:16px; }}
 main {{ max-width:820px; margin:0 auto; padding:12px 12px 40px; }}
 h2 {{ font-size:15px; margin:22px 0 8px; color:var(--ink); }}
 h2 .cnt {{ color:var(--muted); font-weight:normal; font-size:13px; }}
 .card {{ background:#fff; border:1px solid var(--line); border-radius:10px;
          padding:10px 12px; margin-bottom:8px; }}
 .card.trig {{ border-color:#bcd3ff; box-shadow:0 0 0 2px #e8f0ff inset; }}
 .line1 {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
 .name {{ font-weight:600; font-size:15px; }}
 .code {{ color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; }}
 .line2 {{ margin-top:6px; display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:12.5px; }}
 .stage {{ color:#fff; padding:1px 8px; border-radius:20px; font-size:12px; }}
 .board {{ background:#eef2f8; color:#48566e; padding:1px 7px; border-radius:20px; }}
 .meta {{ color:var(--muted); }}
 .muted {{ color:var(--muted); }}
 .line3 {{ margin-top:7px; font-size:12.5px; }}
 .line3 a {{ color:var(--blue); text-decoration:none; }}
 .line3 a:hover {{ text-decoration:underline; }}
 .badge {{ font-size:11px; padding:1px 7px; border-radius:20px; }}
 .badge.star {{ background:#1f6feb; color:#fff; }}
 .badge.new {{ background:#e8462d; color:#fff; }}
 .badge.chg {{ background:#b08900; color:#fff; }}
 footer {{ text-align:center; color:var(--muted); font-size:12px; padding:20px; }}
</style></head><body>
<header>
  <h1>IPO三棱镜 · 每日监控</h1>
  <div class="sub">港交所 / 上交所 / 深交所 / 北交所 &nbsp;·&nbsp; 更新于 {updated_at}</div>
  <div class="stats"><b>{len(filings)}</b> 家在管线 &nbsp;·&nbsp; <b>{trigger_total}</b> 家 ★可选题 &nbsp;·&nbsp; 今日新增 <b>{new_total}</b></div>
</header>
<main>{''.join(sections)}</main>
<footer>★可选题 = 已过会 / 已发聆讯后资料集及以后 &nbsp;·&nbsp; 结尾与核心判断仍由你定,机器只做监控与提示</footer>
</body></html>"""
