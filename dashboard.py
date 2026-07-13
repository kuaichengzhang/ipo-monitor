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


def _row(f, new_uids, changed_uids, dossier_map):
    return {
        "ex": f.exchange, "bd": f.board, "code": f.stock_code or "",
        "name": f.company_name, "stage": f.stage, "status": f.status,
        "spon": f.sponsor or "", "date": f.page_updated or "",
        "trig": is_trigger(f.stage),
        "new": f.uid in new_uids, "chg": f.uid in changed_uids,
        "pros": f.prospectus_url or "", "phip": f.phip_url or "",
        "src": f.source_url or "",
        "dossier": dossier_map.get(f.company_name, ""),
        "mk": "/".join(f.markers) if f.markers else "",
        "py": _initials(f.company_name),
        "pys": _initials(f.sponsor or ""),
    }


def generate_dashboard(filings, new_uids=None, changed_uids=None,
                       updated_at=None, dossier_map=None) -> str:
    new_uids = new_uids or set()
    changed_uids = changed_uids or set()
    dossier_map = dossier_map or {}
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

    return r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IPO三棱镜 · 每日监控</title>
<style>
 :root { --blue:#1f6feb; --ink:#1a2233; --muted:#8a94a6; --line:#e6ebf2; --bg:#f6f8fb; }
 * { box-sizing:border-box; } body { margin:0; font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif; background:var(--bg); color:var(--ink); line-height:1.5; }
 header { background:linear-gradient(135deg,#0f4faf,#1f6feb); color:#fff; padding:18px 16px; }
 header h1 { margin:0; font-size:19px; } header .sub { opacity:.9; font-size:13px; margin-top:4px; }
 header .stats { margin-top:8px; font-size:13px; } header .stats b { font-size:16px; }
 main { max-width:860px; margin:0 auto; padding:12px 12px 60px; }
 .controls { position:sticky; top:0; background:var(--bg); padding:10px 0; z-index:5; border-bottom:1px solid var(--line); }
 .search { width:100%; padding:9px 12px; border:1px solid var(--line); border-radius:8px; font-size:14px; }
 .tabs { display:flex; gap:6px; margin-top:8px; flex-wrap:wrap; }
 .tab { border:1px solid var(--line); background:#fff; border-radius:20px; padding:4px 12px; font-size:13px; cursor:pointer; }
 .tab.on { background:var(--blue); color:#fff; border-color:var(--blue); }
 .chips { display:flex; gap:6px; margin-top:6px; flex-wrap:wrap; align-items:center; }
 .chip { border:1px solid var(--line); background:#fff; border-radius:20px; padding:2px 10px; font-size:12px; cursor:pointer; }
 .chip.on { background:#e8f0ff; border-color:#bcd3ff; color:#1a5fd0; }
 .count { color:var(--muted); font-size:12px; margin-left:auto; }
 .card { background:#fff; border:1px solid var(--line); border-radius:10px; padding:10px 12px; margin-top:8px; }
 .card.trig { border-color:#bcd3ff; box-shadow:0 0 0 2px #e8f0ff inset; }
 .l1 { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
 .name { font-weight:600; font-size:15px; } .code { color:var(--muted); font-size:12px; }
 .l2 { margin-top:6px; display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:12.5px; }
 .stage { color:#fff; padding:1px 8px; border-radius:20px; font-size:12px; }
 .board { background:#eef2f8; color:#48566e; padding:1px 7px; border-radius:20px; }
 .meta { color:var(--muted); } .l3 { margin-top:7px; font-size:12.5px; display:flex; gap:12px; flex-wrap:wrap; }
 .l3 a { color:var(--blue); text-decoration:none; } .l3 a:hover { text-decoration:underline; }
 .btn-dossier { background:var(--blue); color:#fff !important; padding:2px 10px; border-radius:6px; }
 .badge { font-size:11px; padding:1px 7px; border-radius:20px; }
 .badge.star { background:#1f6feb; color:#fff; } .badge.new { background:#e8462d; color:#fff; } .badge.chg { background:#b08900; color:#fff; }
 .pager { display:flex; gap:6px; margin-top:16px; justify-content:center; align-items:center; flex-wrap:wrap; }
 .pager button { border:1px solid var(--line); background:#fff; border-radius:8px; padding:6px 12px; font-size:13px; cursor:pointer; min-width:38px; }
 .pager button.cur { background:var(--blue); color:#fff; border-color:var(--blue); }
 .pager button:disabled { opacity:.4; cursor:default; }
 .pager .gap { color:var(--muted); }
 .pager select { border:1px solid var(--line); border-radius:8px; padding:6px 8px; font-size:13px; background:#fff; }
 .pager .jump { width:56px; padding:6px 8px; border:1px solid var(--line); border-radius:8px; font-size:13px; }
 mark { background:#ffe9a8; padding:0 1px; border-radius:2px; }
 footer { text-align:center; color:var(--muted); font-size:12px; padding:20px; }
</style></head><body>
<header>
  <h1>IPO三棱镜 · 每日监控</h1>
  <div class="sub">港交所 / 上交所 / 深交所 / 北交所 · 更新于 __UPDATED__</div>
  <div class="stats"><b>__TOTAL__</b> 家在管线 · <b>__TRIG__</b> 家 ★可选题 · __NEWLABEL__ · <b>__DOSSIERS__</b> 篇拆解档案</div>
</header>
<main>
  <div class="controls">
    <input class="search" id="q" placeholder="搜公司名 / 保荐机构 / 代码…">
    <div class="tabs"><button class="tab on" data-ex="">全部</button>__EXTABS__</div>
    <div class="chips">
      <span class="chip" data-f="trig">只看 ★可选题</span>
      <span class="chip" data-f="new">只看 新增/变化</span>
      <span class="chip" data-f="dossier">有拆解档案</span>
      <span class="chip" data-f="recent">近30天有动态</span>
      <span class="count" id="count"></span>
    </div>
  </div>
  <div id="list"></div>
  <div class="pager" id="pager"></div>
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
           page:Math.max(1, parseInt(p.get('p')||'1')||1),
           size:[20,50,100].includes(parseInt(p.get('s')))?parseInt(p.get('s')):50 };
}
let state = readState();
function writeState(){
  const p = new URLSearchParams();
  if(state.q) p.set('q', state.q);
  if(state.ex) p.set('ex', state.ex);
  const f = Object.keys(state.flags).filter(k=>state.flags[k]).join(',');
  if(f) p.set('f', f);
  if(state.page>1) p.set('p', state.page);
  if(state.size!==50) p.set('s', state.size);
  history.replaceState(null,'','#'+p.toString());
}
// —— 查询:多关键词 AND;每个词命中 公司名/保荐/代码/板块/阶段 或 拼音首字母 ——
function recentCut(){ const d=new Date(); d.setDate(d.getDate()-30); return d.toISOString().slice(0,10); }
function matches(r, terms){
  return terms.every(t => r.name.toLowerCase().includes(t) || r.spon.toLowerCase().includes(t)
    || r.code.includes(t) || r.bd.includes(t) || r.stage.includes(t) || r.status.includes(t)
    || (r.py && r.py.includes(t)) || (r.pys && r.pys.includes(t)));
}
function filtered(){
  const terms = state.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const cut = recentCut();
  let rows = DATA.filter(r => {
    if(state.ex && r.ex!==state.ex) return false;
    if(state.flags.trig && !r.trig) return false;
    if(state.flags.new && !(r.new||r.chg)) return false;
    if(state.flags.dossier && !r.dossier) return false;
    if(state.flags.recent && !(r.date && r.date>=cut)) return false;
    if(terms.length && !matches(r, terms)) return false;
    return true;
  });
  rows.sort((a,b)=> (b.date||'').localeCompare(a.date||'') || ORDER.indexOf(a.stage)-ORDER.indexOf(b.stage));
  return rows;
}
function esc(s){ return (s||'').replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function hl(s, terms){
  let out = esc(s);
  for(const t of terms){ if(!t) continue;
    const re = new RegExp('('+t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','gi');
    out = out.replace(re,'<mark>$1</mark>');
  }
  return out;
}
function card(r, terms){
  const badges = (r.trig?'<span class="badge star">★ 可选题</span>':'') + (r.new?'<span class="badge new">新</span>':(r.chg?'<span class="badge chg">状态更新</span>':''));
  const links = [];
  if(r.dossier) links.push('<a class="btn-dossier" href="'+esc(r.dossier)+'">拆解档案</a>');
  if(r.phip) links.push('<a href="'+esc(r.phip)+'" target="_blank">聆讯后资料集</a>');
  if(r.pros && r.pros!==r.phip) links.push('<a href="'+esc(r.pros)+'" target="_blank">招股书</a>');
  if(r.src) links.push('<a href="'+esc(r.src)+'" target="_blank">交易所审核页</a>');
  return '<div class="card '+(r.trig?'trig':'')+'">'
    +'<div class="l1"><span class="code">'+esc(r.code)+'</span><span class="name">'+hl(r.name,terms)+'</span>'+(r.mk?'<span class="board">'+esc(r.mk)+'</span>':'')+badges+'</div>'
    +'<div class="l2"><span class="stage" style="background:'+(COLORS[r.stage]||'#5b7db1')+'">'+esc(r.stage)+'</span>'
    +'<span class="meta">'+esc(r.status)+'</span><span class="board">'+esc(r.bd)+'</span>'
    +(r.spon?'<span class="meta">保荐 '+hl(r.spon,terms)+'</span>':'')+(r.date?'<span class="meta">'+esc(r.date)+'</span>':'')+'</div>'
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
  writeState();
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
render();
</script>
</body></html>""".replace("__UPDATED__", updated_at) \
   .replace("__TOTAL__", str(len(rows))).replace("__TRIG__", str(trigger_total)) \
   .replace("__NEWLABEL__", new_label).replace("__DOSSIERS__", str(dossier_total)) \
   .replace("__EXTABS__", ex_tabs).replace("__DATA__", data_json) \
   .replace("__COLORS__", stage_colors_json).replace("__ORDER__", stage_order_json)
