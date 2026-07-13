"""硬约束测试 —— 证明机器不会越线。

这是整套系统里最重要的测试:它验证的不是"功能能跑",而是"品牌红线焊死了"。
对应规格书「机器永远不做的四件事」。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extractor import Page, extract_all, extract_metric, MISSING, METRIC_PATTERNS  # noqa: E402
from tension import score_tensions, MAX_CANDIDATES, PRESELECT  # noqa: E402
from skeleton import generate_skeleton  # noqa: E402


# 构造一份"招股书"页面文本(模拟真实排版:数字散在句子里,页码即出处)
FAKE_PAGES = [
    Page(1, "本公司按照国际财务报告准则编制财务报表。报告期为2023年、2024年及2025年。"),
    Page(7, "于往绩记录期间,我们的营业收入分别为人民币12.5亿元、18.3亿元及24.1亿元。"),
    Page(8, "同期我们录得净亏损人民币3.2亿元、2.8亿元及1.9亿元,主要由于研发开支及产能爬坡。"),
    Page(9, "我们的毛利率由2023年的8.4%上升至2025年的23.7%。"),
    Page(12, "研发费用占同期收入的比例分别为31.5%、28.9%及26.4%。"),
    Page(15, "来自前五大客户的收入占总收入的68.2%,其中最大客户占比达41.3%。"),
    Page(18, "产能利用率于报告期分别为73.5%、81.2%及86.4%。"),
    Page(21, "根据弗若斯特沙利文的资料,按2025年出货量计,我们在中国碳化硅功率模块市场排名第三,市场份额为6.8%。"),
    Page(30, "经营活动所用的现金流量净额为人民币4.1亿元净流出。"),
    Page(45, "所得款项净额约为25.6亿港元,其中约60%将用于产能建设及扩产。"),
]


def test_every_number_has_page_cite():
    """铁律:任何输出的数字都必须挂页码。"""
    metrics = extract_all(FAKE_PAGES)
    for name, m in metrics.items():
        for e in m.evidences:
            assert isinstance(e.page, int) and e.page > 0, f"{name} 的证据缺页码"
            assert e.cite() == f"【招股书 p.{e.page}】"
    # 渲染出来的每条都带【招股书 p.X】
    for name, m in metrics.items():
        if m.found:
            assert "【招股书 p." in m.render(), f"{name} 渲染缺出处"
    print("✓ 铁律:所有提取到的数字都挂着页码出处")


def test_missing_is_flagged_never_fabricated():
    """招股书里没有的指标 -> 必须标红待核,绝不能凭空出现一个数。"""
    # 一份几乎空白的招股书:只有会计准则,没有任何财务数字
    thin = [Page(1, "本公司按照国际财务报告准则编制财务报表。")]
    metrics = extract_all(thin)

    assert metrics["营收"].render() == MISSING
    assert metrics["毛利率"].render() == MISSING
    assert metrics["客户集中度"].render() == MISSING
    assert not metrics["产能利用率"].found

    cands = score_tensions(metrics)
    doc = generate_skeleton("空白测试公司", "港交所", "主板", "过会/通过", None, metrics, cands)

    # 骨架里必须出现待核标记,且不能凭空出现任何未在原文的数字
    assert MISSING in doc
    for fabricated in ["12.5亿", "68.2%", "6.8%", "25.6亿"]:
        assert fabricated not in doc, f"骨架里出现了原文没有的数字:{fabricated}"
    print("✓ 缺出处的指标一律标红待核,机器绝不编造数字")


def test_spine_and_ending_always_blank():
    """硬约束 1&2:脊和结尾永远留空,机器不写。"""
    metrics = extract_all(FAKE_PAGES)
    cands = score_tensions(metrics)
    doc = generate_skeleton("测试半导体", "港交所", "主板", "过会/通过",
                            "https://example.com/p.pdf", metrics, cands)

    assert "【脊 · 留空】" in doc
    assert "机器不写,由 Paodekuai 定" in doc
    assert "【结尾 · 留空】" in doc
    assert "机器不碰" in doc
    print("✓ 硬约束:脊与结尾永远留空,机器不写")


def test_no_verdict_language():
    """硬约束 3:不下定性结论。骨架里不得出现判断/煽动性措辞。"""
    metrics = extract_all(FAKE_PAGES)
    doc = generate_skeleton("测试半导体", "港交所", "主板", "过会/通过", None,
                            metrics, score_tensions(metrics))
    banned = ["涉嫌", "造假", "值得买", "不值得", "必然", "骗局", "割韭菜", "暴雷", "危险信号", "警惕"]
    for w in banned:
        assert w not in doc, f"骨架出现了定性/煽动措辞:{w}"
    print("✓ 硬约束:骨架无定性结论、无煽动措辞")


def test_tension_scoring_and_caps():
    """张力候选:越阈值入选、封顶 5、预选 3;信号措辞为中性反差陈述。"""
    metrics = extract_all(FAKE_PAGES)
    cands = score_tensions(metrics)
    assert len(cands) <= MAX_CANDIDATES

    themes = [c.theme for c in cands]
    # 客户集中度 68.2%(>50% 阈值)应当入选且分数高
    assert "客户集中度" in themes
    cust = next(c for c in cands if c.theme == "客户集中度")
    assert cust.score >= 3
    assert any("68.2" in s for s in cust.signals)
    # 产能利用率未满 + 募资扩产 -> 反差信号
    if "产能与扩产" in themes:
        cap = next(c for c in cands if c.theme == "产能与扩产")
        assert any("未满" in s or "低于满产" in s for s in cap.signals)

    doc = generate_skeleton("测试半导体", "港交所", "主板", "过会/通过", None, metrics, cands)
    pillars = doc.count("### 支柱")
    assert pillars <= PRESELECT
    print(f"✓ 张力打分:{len(cands)} 个候选(封顶{MAX_CANDIDATES}),预选 {pillars} 根支柱;客户集中度68.2%正确触发阈值")


def test_market_share_verbatim():
    """市占率 claim 必须原文照录,且识别委托机构(弗若斯特沙利文)。"""
    metrics = extract_all(FAKE_PAGES)
    ms = metrics["市占率/排名"]
    assert ms.found
    joined = ms.render()
    assert "弗若斯特沙利文" in joined      # 委托机构被抓到
    assert "排名第三" in joined or "第三" in joined
    assert "【招股书 p.21】" in joined      # 出处正确
    print("✓ 市占率 claim 原文照录,委托机构与页码正确")


if __name__ == "__main__":
    test_every_number_has_page_cite()
    test_missing_is_flagged_never_fabricated()
    test_spine_and_ending_always_blank()
    test_no_verdict_language()
    test_tension_scoring_and_caps()
    test_market_share_verbatim()
    print("\n硬约束全部通过 ✅ —— 机器不编数字、不写脊、不写结尾、不下判断")
