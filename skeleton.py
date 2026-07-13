"""骨架草稿生成 —— 严格按规格书 v0.2。

【机器永远不做的四件事(硬约束,本模块逐条对应)】
1. 不写"脊"(核心矛盾)          -> SPINE 位置永远输出占位符
2. 不写结尾                      -> ENDING 位置永远输出占位符
3. 不下定性结论                  -> 只输出提取到的数字与中性反差陈述
4. 不填无页码出处的数字          -> 全部数值来自 Evidence(必带 page),缺则 [缺出处·待核]
"""
from __future__ import annotations

from datetime import datetime

from extractor import Metric, MISSING
from tension import TensionCandidate, preselect_pillars

SPINE_PLACEHOLDER = (
    "> 【脊 · 留空】本文的核心矛盾 / 那句站得住的真话。\n"
    "> **机器不写,由 Paodekuai 定。** 下方是机器筛出的张力候选,供你选一个当脊。"
)

ENDING_PLACEHOLDER = (
    "> 【结尾 · 留空】永远留给 Paodekuai 自己的声音。**机器不碰。**"
)

CHECKLIST = """- [ ] 每个数字的页码是否对得上原文
- [ ] 市占率 / "第一" / 排名类 claim:是否抄全了口径限定语 + 委托机构(F&S/灼识/CIC/Omdia)并原文照录
- [ ] 会计准则口径是否统一(IFRS vs PRC GAAP),报告期是否标明
- [ ] 政府补助 / 非经常性损益是否已从核心经营里剥出
- [ ] 优先股 IFRS 金融负债是否存在(可能是 IPO 时点的倒逼因素)
- [ ] 有没有跨商业模式硬比数字
- [ ] `[缺出处·待核]` 标红项是否已清零"""

SNAPSHOT_ORDER = [
    "会计准则", "营收", "净利润/净亏损", "经调整净利润/亏损", "毛利率",
    "研发投入/研发费用率", "客户集中度", "产能利用率", "政府补助/非经常性损益",
    "经营活动现金流", "单价/ASP", "市占率/排名", "关联交易", "拟募资额", "扭亏时间表",
]


def _snapshot_table(metrics: dict[str, Metric]) -> str:
    rows = ["| 指标 | 提取值(带出处) |", "|---|---|"]
    for name in SNAPSHOT_ORDER:
        m = metrics.get(name)
        val = m.render() if m else MISSING
        if val == MISSING:
            val = f"**{MISSING}**"      # 标红(markdown 加粗提示)
        rows.append(f"| {name} | {val} |")
    return "\n".join(rows)


def _pillar_block(idx: int, cand: TensionCandidate) -> str:
    hard = cand.evidences[0] if cand.evidences else None
    hard_line = hard.render() if hard else f"**{MISSING}**"
    situation = hard.snippet if hard else f"**{MISSING}**"
    tension_lines = "\n".join(
        f"  - {s}" for s in cand.signals
    ) or f"  - **{MISSING}**"
    cites = " ".join(sorted({e.cite() for e in cand.evidences}))
    return f"""### 支柱{idx}:{cand.theme}

- **硬数字**:{hard_line}
- **情况**(招股书原文片段,未经改写):{situation}
- **张力**(机器只陈述数字反差,不下判断):
{tension_lines}
  {cites}
- **行业落点**:`这不只是这一家 —— [待人写:接到产业层面]`
"""


def generate_skeleton(company: str, exchange: str, board: str, stage: str,
                      prospectus_url: str | None,
                      metrics: dict[str, Metric],
                      candidates: list[TensionCandidate]) -> str:
    pillars = preselect_pillars(candidates)
    missing_count = sum(1 for n in SNAPSHOT_ORDER if not (metrics.get(n) and metrics[n].found))

    cand_list = "\n".join(f"{i+1}. {c.render()}" for i, c in enumerate(candidates)) or "(未提取到越过阈值的张力候选)"
    pillar_blocks = "\n".join(_pillar_block(i + 1, c) for i, c in enumerate(pillars)) or "(无)"

    return f"""# 【骨架草稿】{company}

> 机器生成 · {datetime.now().strftime('%Y-%m-%d')} · 仅为带出处的骨架,**脊与结尾留空**
> {exchange} · {board} · {stage}
> 招股书:{prospectus_url or MISSING}
> ⚠ 本文档所有数字均来自招股书页面文本并标注页码;未提取到出处的指标一律标记 **{MISSING}**,机器不填充。
> 当前有 **{missing_count}** 项待核。

---

## 一、关键数字快照(每格带页码)

{_snapshot_table(metrics)}

---

## 二、张力候选(机器筛出,供你选脊;越阈值入选,封顶 5,预选前 3 为支柱)

{cand_list}

---

## 三、骨架

{SPINE_PLACEHOLDER}

{pillar_blocks}

{ENDING_PLACEHOLDER}

---

## 四、待核清单

{CHECKLIST}
"""
