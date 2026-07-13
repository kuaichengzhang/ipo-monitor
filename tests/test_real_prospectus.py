"""对真实招股书文本的校准测试(基本半导体英文版摘录,页码真实)。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from basic_semi_en_excerpts import REAL_PAGES  # noqa: E402
from extractor import Page, extract_all, normalize_text, cid_trap_ratio, MISSING  # noqa: E402
from tension import score_tensions  # noqa: E402
from skeleton import generate_skeleton  # noqa: E402

PAGES = [Page(n, t) for n, t in sorted(REAL_PAGES.items())]


def test_normalize_cjk_spacing():
    assert normalize_text("全 球發 售（ 於 中 華") == "全球發售（於中華"
    print("✓ 中文字符间空格归一化(实测港股PDF提取形态)")


def test_cid_trap_detection():
    cn_trap = [Page(i, "–16–287,534,442HH27.49H31.62H(1)....") for i in range(1, 40)]
    assert cid_trap_ratio(cn_trap) < 0.01
    ok = [Page(i, "本公司报告期内营业收入为12.5亿元。") for i in range(1, 40)]
    assert cid_trap_ratio(ok) > 0.5
    print("✓ CID字体陷阱检测:中文占比≈0即报警(基本半导体中文版实测形态)")


def test_extract_real_english():
    m = extract_all(PAGES)
    # 客户集中度:46.4/63.1/40.4,页码17
    cust = m["客户集中度"]
    assert cust.found and "63.1" in cust.render() and "【招股书 p.17】" in cust.render()
    # 经营现金流:1.115亿净流出,页码22
    cf = m["经营活动现金流"]
    assert cf.found and "111.5" in cf.render() and "p.22" in cf.render()
    # 毛利率:84.7%(p13脚注)
    gm = m["毛利率"]
    assert gm.found and any("84.7" in e.value for e in gm.evidences)
    # 扭亏时间表:Path to Profitability(p24)
    turn = m["扭亏时间表"]
    assert turn.found and any(e.page == 24 for e in turn.evidences)
    # 拟募资:HK$658.7M(p23)
    pr = m["拟募资额"]
    assert pr.found and "658.7" in pr.render()
    # ASP:降价表述(p14)
    asp = m["单价/ASP"]
    assert asp.found and any(e.page in (13, 14) for e in asp.evidences)
    # 市占率claim:F&S 委托机构在句(p16)
    ms = m["市占率/排名"]
    assert ms.found
    print("✓ 真实英文招股书:客户集中度/现金流/毛利率/扭亏/募资/ASP 全部带真页码提取")


def test_tension_on_real():
    m = extract_all(PAGES)
    cands = score_tensions(m)
    themes = [c.theme for c in cands]
    cust = next((c for c in cands if c.theme == "客户集中度"), None)
    assert cust is not None and cust.score >= 3, "63.1% 应触发>50%阈值"
    doc = generate_skeleton("深圳基本半导体股份有限公司", "港交所", "主板",
                            "注册生效/招股", "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0629/2026062900049.pdf",
                            m, cands)
    assert "【脊 · 留空】" in doc and "【结尾 · 留空】" in doc
    assert "63.1" in doc
    print(f"✓ 真实数据张力打分:{len(cands)}候选({', '.join(themes)});骨架脊/尾留空")


if __name__ == "__main__":
    test_normalize_cjk_spacing()
    test_cid_trap_detection()
    test_extract_real_english()
    test_tension_on_real()
    print("\n真实招股书校准全部通过 ✅")
