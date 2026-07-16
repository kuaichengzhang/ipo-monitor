#!/usr/bin/env python3
"""
teardown/run_daily.py  —  财报拆解自动化机械层(无 LLM key 依赖)

职责(只做机械活,分析由 agent 当大脑):
  prepare      从仓库拉取 finreports.json + teardowns.json,筛出"新的年报/半年报",
               下载 PDF 抽关键文本,写入 prep/<uid>.txt 与 pending.json。
  append       把一个拆解卡 JSON 文件追加进本地 teardowns.json(累积式)。
  commit       把本地 teardowns.json PUT 回仓库 main。
  push-file    一次性把本脚本/参考文件推上仓库(初始化用)。

所有仓库读写均走 `gh api`(沙箱内 git 协议不可用)。
"""
import os, sys, json, re, io, argparse, base64, subprocess
from pathlib import Path

REPO = "kuaichengzhang/ipo-monitor"
HERE = Path(__file__).resolve().parent
PREP = HERE / "prep"
CARDS = HERE / "cards"
PENDING = HERE / "pending.json"
LOCAL_TD = HERE / "teardowns.json"
MAX_PER_RUN = 5  # 单日上限,防过载;未处理次日继续

MEDICAL_TAGS = ["医疗健康", "创新药", "生物医药", "生物科技", "医疗器械",
                "CXO", "IVD", "医疗服务", "中药", "疫苗"]

# ---------------- gh helpers ----------------
def _run(args):
    return subprocess.run(args, capture_output=True, text=True)

def gh_get(path):
    p = _run(["gh", "api", f"repos/{REPO}/contents/{path}"])
    if p.returncode != 0:
        raise RuntimeError(f"gh_get {path}: {p.stderr.strip()}")
    obj = json.loads(p.stdout)
    content = base64.b64decode(obj["content"]).decode("utf-8", "replace")
    return content, obj.get("sha")

def _put_args(path, b64, sha, message):
    args = ["gh", "api", "-X", "PUT", f"repos/{REPO}/contents/{path}",
            "-f", f"message={message}", "-f", f"content={b64}", "-f", "branch=main"]
    if sha:
        args += ["-f", f"sha={sha}"]
    return args

def gh_put(path, content_str, sha, message):
    b64 = base64.b64encode(content_str.encode("utf-8")).decode()
    last = None
    for _ in range(3):
        if sha:
            try:
                _, sha = gh_get(path)
            except Exception:
                pass
        p = _run(_put_args(path, b64, sha, message))
        if p.returncode == 0:
            return True, p.stdout
        last = (p.returncode, p.stderr)
    return False, str(last)

# ---------------- detection helpers ----------------
def is_medical(industry, sub):
    s = f"{industry or ''}|{sub or ''}".lower()
    return any(t.lower() in s for t in MEDICAL_TAGS)

def is_target(r):
    rt = r.get("report_type", "") or ""
    if "季报" in rt:
        return False
    return ("年报" in rt) or ("半年报" in rt)

def year_half(s):
    s = s or ""
    m = re.search(r"(20\d{2})", s)
    year = m.group(1) if m else None
    half = ("半" in s) or ("H1" in s.upper())
    return year, half

def existing_keys(td_list):
    keys = set()
    for c in td_list:
        code = c.get("stock_code") or c.get("header", {}).get("ticker")
        hp = c.get("header", {}).get("period", "")
        sr = c.get("_meta", {}).get("source_report", "")
        yh = year_half(hp)
        yh2 = year_half(sr)
        year = yh[0] or yh2[0]
        half = yh[1] or yh2[1]
        if code and year:
            keys.add((str(code), year, half))
    return keys

# ---------------- PDF extraction ----------------
def fetch_and_extract(url, company, period):
    try:
        import pdfplumber, requests
    except ImportError:
        _run([sys.executable, "-m", "pip", "install", "-q", "pdfplumber", "requests"])
        import pdfplumber, requests
    r = requests.get(url, timeout=90)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "").lower()
    if "pdf" not in ctype and not url.lower().endswith(".pdf"):
        raise RuntimeError(f"非 PDF 响应 Content-Type={ctype}")
    pages_text = []
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        n = min(len(pdf.pages), 140)
        for i in range(n):
            try:
                pages_text.append(pdf.pages[i].extract_text() or "")
            except Exception:
                pages_text.append("")
    return condense("\n".join(pages_text), company, period)

def condense(full, company, period):
    out = [f"公司: {company}    报告期: {period}", "=" * 40]
    for kw in ["主要会计数据", "主要财务数据", "会计数据及财务指标", "主要会计数据和财务指标"]:
        idx = full.find(kw)
        if idx >= 0:
            out.append(f"\n【{kw}】\n" + full[idx:idx + 3500])
            break
    patterns = [
        r"营业收入[^\n]{0,40}?(\d[\d,\.]+)\s*元",
        r"归属于上市公司股东的净利润[^\n]{0,40}?(\d[\d,\.]+)\s*元",
        r"归属于上市公司股东的扣除非经常性损益的净利润[^\n]{0,40}?(\d[\d,\.]+)\s*元",
        r"经营活动产生的现金流量净额[^\n]{0,40}?(\d[\d,\.]+)\s*元",
        r"毛利率[^\n]{0,30}?(\d[\d,\.]+)\s*%",
        r"基本每股收益[^\n]{0,30}?([\d,\.]+)\s*元",
        r"总资产[^\n]{0,40}?(\d[\d,\.]+)\s*元",
        r"归属于上市公司股东的净资产[^\n]{0,40}?(\d[\d,\.]+)\s*元",
        r"研发投入[^\n]{0,40}?(\d[\d,\.]+)\s*元",
        r"销售费用[^\n]{0,40}?(\d[\d,\.]+)\s*元",
        r"现金及现金等价物[^\n]{0,40}?(\d[\d,\.]+)\s*元",
        r"每\s*10\s*股[^\n]{0,60}",
    ]
    hits = []
    for pat in patterns:
        for m in re.finditer(pat, full):
            s = max(0, m.start() - 30); e = min(len(full), m.end() + 60)
            hits.append(full[s:e].replace("\n", " ").strip())
            if len(hits) >= 40:
                break
        if len(hits) >= 40:
            break
    if hits:
        out.append("\n【关键指标抓取】\n" + "\n".join(hits[:40]))
    am = re.search(r"(标准无保留意见|保留意见|无法表示意见|否定意见|带强调事项段的无保留意见)", full)
    if am:
        out.append("\n【审计意见】" + am.group(1))
    for kw in ["集采", "医保", "临床", "管线", "研发费用", "核心品种", "在研", "商业化"]:
        idx = full.find(kw)
        if idx >= 0:
            out.append(f"\n【{kw}上下文】" + full[max(0, idx - 80):idx + 160].replace("\n", " ").strip())
    return "\n".join(out)

# ---------------- commands ----------------
def cmd_prepare():
    PREP.mkdir(exist_ok=True)
    CARDS.mkdir(exist_ok=True)
    reports_s, _ = gh_get("data/finreports.json")
    reports = json.loads(reports_s)
    try:
        td_s, sha = gh_get("data/teardowns.json")
        td_list = json.loads(td_s)
    except Exception:
        td_list, sha = [], None
    LOCAL_TD.write_text(json.dumps(td_list, ensure_ascii=False, indent=2), encoding="utf-8")
    done = existing_keys(td_list)
    pending = []
    for r in reports:
        if not is_target(r):
            continue
        code = r.get("stock_code")
        year, half = year_half(r.get("report_period"))
        if not code or not year or (str(code), year, half) in done:
            continue
        url = r.get("announcement_url")
        med = is_medical(r.get("industry"), r.get("sub_industry"))
        rec = {"uid": r.get("uid"), "company": r.get("company_name"), "code": code,
               "report_type": r.get("report_type"), "report_period": r.get("report_period"),
               "exchange": r.get("exchange"), "industry": r.get("industry"),
               "sub_industry": r.get("sub_industry"), "is_18a": r.get("is_18a"),
               "medical": med, "url": url, "announcement_date": r.get("announcement_date")}
        try:
            text = fetch_and_extract(url, r.get("company_name"), r.get("report_period"))
            rec["extract_ok"] = True
        except Exception as e:
            text = f"PDF 提取失败: {e}\n请改用 WebFetch 抓取: {url}\n"
            rec["extract_ok"] = False
            rec["extract_error"] = str(e)[:200]
        (PREP / f"{r.get('uid')}.txt").write_text(text, encoding="utf-8")
        rec["prep"] = f"prep/{r.get('uid')}.txt"
        pending.append(rec)
        if len(pending) >= MAX_PER_RUN:
            break
    PENDING.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[prepare] 待拆解 {len(pending)} 条", file=sys.stderr)
    for p in pending:
        print(f"  - {p['company']} {p['code']} {p['report_type']} 医疗={p['medical']} 提取={'OK' if p['extract_ok'] else 'FAIL'}", file=sys.stderr)
    return pending

def cmd_append(card_path):
    card = json.loads(Path(card_path).read_text(encoding="utf-8"))
    td = json.loads(LOCAL_TD.read_text(encoding="utf-8")) if LOCAL_TD.exists() else []
    td.append(card)
    LOCAL_TD.write_text(json.dumps(td, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[append] 已追加, 当前共 {len(td)} 张卡", file=sys.stderr)

def cmd_commit():
    if not LOCAL_TD.exists():
        print("[commit] 无本地 teardowns.json", file=sys.stderr); return False
    content = LOCAL_TD.read_text(encoding="utf-8")
    try:
        _, sha = gh_get("data/teardowns.json")
    except Exception:
        sha = None
    ok, res = gh_put("data/teardowns.json", content, sha,
                     "chore: 自动追加财报拆解卡 (teardown bot)")
    print(("[commit] OK" if ok else f"[commit] FAIL {res}"), file=sys.stderr)
    return ok

def cmd_push_file(local, repo_path, message):
    txt = Path(local).read_text(encoding="utf-8")
    try:
        _, sha = gh_get(repo_path)
    except Exception:
        sha = None
    ok, res = gh_put(repo_path, txt, sha, message)
    print(("[push] OK" if ok else f"[push] FAIL {res}"), file=sys.stderr)
    return ok

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("prepare")
    p_app = sub.add_parser("append"); p_app.add_argument("card_path")
    sub.add_parser("commit")
    p_push = sub.add_parser("push-file")
    p_push.add_argument("local"); p_push.add_argument("repo_path"); p_push.add_argument("-m", "--message", default="push file")
    args = ap.parse_args()
    if args.cmd == "prepare":
        cmd_prepare()
    elif args.cmd == "append":
        cmd_append(args.card_path)
    elif args.cmd == "commit":
        cmd_commit()
    elif args.cmd == "push-file":
        cmd_push_file(args.local, args.repo_path, args.message)
    else:
        ap.print_help()

if __name__ == "__main__":
    main()
