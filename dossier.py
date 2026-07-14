"""拆解档案生成器 —— "说人话"的机器底稿,带校验闸门。

产品定位(Paodekuai 2026-07 拍板):
- 档案 ≠ 三棱镜成稿。成稿(脊/结尾/判断)永远由人写;档案只做"罗列清楚"。
- 每家 ★可选题 公司自动建档,挂在看板网站,页面标注"机器生成底稿"。

流水线:招股书按页文本 -> 分块喂给 DeepSeek API 按六板块模板写作 -> 校验闸门 -> 出稿/打回。

【校验闸门(代码强制,模型骗不过)】
1. 含数字的句子必须挂 【招股书... p.N】 出处,否则该句替换为 [缺出处·待核]
2. 定性/煽动词(涉嫌/造假/暴雷/割韭菜/警惕/骗局/必然/值得买/不值得)出现即打回该句
3. 引用页码回查:句中数字必须真的出现在所引页的原文里,对不上即打回该句
4. 免责与"机器生成底稿"标识强制附加
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from extractor import Page, normalize_text

BANNED = ["涉嫌", "造假", "暴雷", "割韭菜", "警惕", "骗局", "必然", "值得买", "不值得买",
          "建议买入", "建议卖出", "必将", "肯定会"]

CITE_RE = re.compile(r"【招股书[^】]*p\.(\d+)】")
MISSING = "[缺出处·待核]"

SECTIONS = [
    "一、这是个什么生意",
    "二、赚不赚钱",
    "三、过去怎么走的,未来怎么说的",
    "四、行业什么样",
    "五、生意里的数字反差",
    "六、值得关注的点 + 待核清单",
]

PROMPT_TEMPLATE = """你是「IPO三棱镜」的拆解档案写手。基于下面提供的招股书逐页文本,为公司写一份"说人话"的拆解底稿。

铁律(违反即废稿):
1. 每一个数字后面必须紧跟出处【招股书 p.N】,N 必须是下方文本中该数字真实所在的页码。文本里没有的数字,一个都不许写。
2. 不下任何定性判断:不写"涉嫌/造假/风险大/不行/值得买"。"问题"一律写成客观的数字反差。
3. 市占率/排名/"第一"类表述:必须连同口径限定语和委托研究机构名原文照录。
4. 拿不准的信息写 [缺出处·待核],不许编。
5. 语言:短句,大白话,像给聪明但不懂财务的朋友讲清楚这门生意。

按以下六个板块输出 markdown(标题原样保留):
{sections}

公司:{company}
招股书逐页文本(格式为 [p.页码] 内容):
{pages_text}
"""


# ===== 医疗专属招股书拆解 (6维度) =====
MEDICAL_SECTIONS = [
    "一、核心管线与产品",
    "二、临床试验阶段",
    "三、适应症与市场空间",
    "四、研发投入",
    "五、竞争格局",
    "六、核心风险 + 待核清单",
]

MEDICAL_PROMPT_TEMPLATE = """你是「IPO三棱镜」的医疗行业拆解档案写手，专注于医药/生物科技公司的招股书拆解。基于下面提供的招股书逐页文本,为公司写一份"说人话"的拆解底稿。

铁律(违反即废稿):
1. 每一个数字后面必须紧跟出处【招股书 p.N】,N 必须是下方文本中该数字真实所在的页码。文本里没有的数字,一个都不许写。
2. 不下任何定性判断:不写"涉嫌/造假/风险大/不行/值得买"。"问题"一律写成客观的数字反差。
3. 市占率/排名/"第一"类表述:必须连同口径限定语和委托研究机构名原文照录。
4. 拿不准的信息写 [缺出处·待核],不许编。
5. 语言:短句,大白话,像给聪明但不懂医药的朋友讲清楚这家公司在做什么药、做到哪了。

特别关注:
- 在研管线的产品名称、靶点、作用机制
- 每条管线的临床阶段（临床前/I期/II期/III期/NDA/已上市）
- 适应症及对应的市场规模数据
- 累计研发投入、研发费用率、烧钱速度
- 与同靶点/同适应症竞品的对比

按以下六个板块输出 markdown(标题原样保留):
{sections}

公司:{company}
招股书逐页文本(格式为 [p.页码] 内容):
{pages_text}
"""


@dataclass
class GateReport:
    """校验闸门报告。"""
    passed_sentences: int = 0
    rejected_no_cite: list[str] = field(default_factory=list)     # 有数字无出处
    rejected_banned: list[str] = field(default_factory=list)      # 定性词
    rejected_bad_cite: list[str] = field(default_factory=list)    # 页码对不上

    @property
    def clean(self) -> bool:
        return not (self.rejected_no_cite or self.rejected_banned or self.rejected_bad_cite)


def _sentences(md: str):
    """按句拆(保留 markdown 行结构:逐行内再按句号拆)。"""
    for line in md.splitlines():
        if line.strip().startswith(("#", ">", "-", "*", "|")) or not line.strip():
            yield line, True   # 结构行整行处理
        else:
            yield line, True


def _numbers_in(text: str) -> list[str]:
    # 去掉出处标记和年份后再找数字(年份/页码本身不算"需出处的数字")
    t = CITE_RE.sub("", text)
    # 用数字边界而非 \b(后者在中文"年"前不生效,导致"2023年"中的2023未被过滤)
    t = re.sub(r"(?<![0-9])(?:19|20)\d{2}(?![0-9])", "", t)
    return re.findall(r"\d[\d,,]*(?:\.\d+)?", t)


def _num_variants(num: str) -> set[str]:
    n = num.replace(",", "").replace(",", "")
    out = {num, n}
    if "." in n:
        out.add(n.rstrip("0").rstrip("."))
    # 千分位版本
    try:
        if "." in n:
            i, f = n.split(".")
            out.add(f"{int(i):,}.{f}")
        else:
            out.add(f"{int(n):,}")
    except ValueError:
        pass
    return out


def gate(md: str, pages: list[Page]) -> tuple[str, GateReport]:
    """校验闸门:逐行检查,违规行静默移除(不污染正文),末尾汇总待核清单。返回(净化稿, 报告)。"""
    page_text = {p.number: normalize_text(p.text or "").replace(",", ",") for p in pages}
    report = GateReport()
    out_lines = []

    for line in md.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue

        # 1) 定性词
        hit_banned = next((w for w in BANNED if w in line), None)
        if hit_banned:
            report.rejected_banned.append(f"[{hit_banned}] {stripped[:60]}")
            continue  # 静默移除,不污染正文

        nums = _numbers_in(line)
        cites = [int(m) for m in CITE_RE.findall(line)]

        # 2) 有数字必须有出处(允许行内已是待核标记)
        if nums and not cites and MISSING not in line:
            report.rejected_no_cite.append(stripped[:70])
            continue  # 静默移除

        # 3) 页码回查:行内每个数字须出现在所引任一页的原文中
        if nums and cites:
            joined = "".join(page_text.get(c, "") for c in cites)
            joined_nospace = joined.replace(" ", "")
            bad = None
            for num in nums:
                variants = _num_variants(num)
                if not any(v in joined or v in joined_nospace for v in variants):
                    bad = num
                    break
            if bad is not None:
                report.rejected_bad_cite.append(f"[{bad}] {stripped[:60]}")
                continue  # 静默移除

        report.passed_sentences += 1
        out_lines.append(line)

    # 末尾追加待核清单(紧凑汇总,不逐条占行)
    total_rejected = len(report.rejected_no_cite) + len(report.rejected_banned) + len(report.rejected_bad_cite)
    if total_rejected:
        out_lines.append("")
        out_lines.append(f"---")
        out_lines.append(f"*闸门拦截 {total_rejected} 句（无出处 {len(report.rejected_no_cite)} · 定性词 {len(report.rejected_banned)} · 页码对不上 {len(report.rejected_bad_cite)}），已从正文移除。*")

    return "\n".join(out_lines), report


def build_prompt(company: str, pages: list[Page], max_chars: int = 120000,
                 medical: bool = False) -> str:
    chunks, used = [], 0
    for p in pages:
        t = normalize_text(p.text or "").strip()
        if not t:
            continue
        block = f"[p.{p.number}] {t}"
        if used + len(block) > max_chars:
            break
        chunks.append(block)
        used += len(block)
    template = MEDICAL_PROMPT_TEMPLATE if medical else PROMPT_TEMPLATE
    sections = "\n".join(MEDICAL_SECTIONS if medical else SECTIONS)
    return template.format(
        sections=sections, company=company, pages_text="\n\n".join(chunks))


def call_deepseek(prompt: str, model: str = "deepseek-chat", max_tokens: int = 8000) -> str:
    """调用 DeepSeek API(需环境变量 DEEPSEEK_API_KEY)。"""
    import requests
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY(GitHub Secrets 或环境变量)")
    resp = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
        json={"model": model, "max_tokens": max_tokens, "temperature": 0.3,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


FOOTER = ("\n\n---\n*机器生成底稿 · 所有数字均应带页码出处,未取得出处的一律标红待核;"
          "机器不填充、不定性、不给买卖建议。三棱镜成稿(脊/结尾/判断)由作者本人撰写。*\n")


def generate_dossier(company: str, meta_line: str, pages: list[Page],
                     llm=call_deepseek, medical: bool = False) -> tuple[str, GateReport]:
    """全流程:prompt -> LLM -> 校验闸门 -> 档案。llm 可注入(测试用假模型)。"""
    raw = llm(build_prompt(company, pages, medical=medical))
    cleaned, report = gate(raw, pages)
    tag = "【医疗拆解档案】" if medical else "【拆解档案】"
    head = (f"# {tag}{company}\n\n> {meta_line}\n"
            f"> 机器生成底稿 · 校验闸门:{report.passed_sentences} 句通过,"
            f"{len(report.rejected_no_cite)+len(report.rejected_banned)+len(report.rejected_bad_cite)} 句拦截\n\n")
    return head + cleaned + FOOTER, report


# —— 档案 markdown -> 简易 HTML(无第三方依赖,供看板链接直接打开)——
_MD_CSS = """<style>body{max-width:760px;margin:0 auto;padding:24px 16px 60px;
font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.75;color:#1a2233;background:#fff}
h1{font-size:22px;border-bottom:2px solid #1f6feb;padding-bottom:8px}h2{font-size:17px;margin-top:28px;color:#0f4faf}
blockquote{border-left:3px solid #bcd3ff;background:#f6f8fb;margin:8px 0;padding:8px 12px;color:#48566e;font-size:13.5px}
li{margin:4px 0}hr{border:none;border-top:1px solid #e6ebf2;margin:24px 0}
strong{color:#1a5fd0}a{color:#1f6feb}.back{font-size:13px}</style>"""


def md_to_html(md: str, title: str = "拆解档案") -> str:
    import html as _h
    import re as _re
    out, in_ul, in_bq = [], False, False
    for line in md.splitlines():
        s = line.rstrip()
        esc = _h.escape(s)
        # 行内:加粗
        esc = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        if s.startswith("- ") or s.startswith("* "):
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append(f"<li>{esc[2:]}</li>"); continue
        if in_ul:
            out.append("</ul>"); in_ul = False
        if s.startswith(">"):
            if not in_bq:
                out.append("<blockquote>"); in_bq = True
            out.append(esc.lstrip("&gt;").strip() + "<br>"); continue
        if in_bq:
            out.append("</blockquote>"); in_bq = False
        if s.startswith("### "):
            out.append(f"<h3>{esc[4:]}</h3>")
        elif s.startswith("## "):
            out.append(f"<h2>{esc[3:]}</h2>")
        elif s.startswith("# "):
            out.append(f"<h1>{esc[2:]}</h1>")
        elif s.strip() in ("---", "***"):
            out.append("<hr>")
        elif s.strip():
            out.append(f"<p>{esc}</p>")
    if in_ul:
        out.append("</ul>")
    if in_bq:
        out.append("</blockquote>")
    body = "\n".join(out)
    return (f"<!doctype html><html lang=\"zh\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{_h.escape(title)}</title>{_MD_CSS}</head><body>"
            f"<p class=\"back\"><a href=\"../../index.html\">← 返回监控看板</a></p>{body}</body></html>")
