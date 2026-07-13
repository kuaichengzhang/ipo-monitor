"""拆解档案 + 校验器测试:金样例必须通过;编造数字必须被抓。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from basic_semi_en_excerpts import REAL_PAGES  # noqa: E402
from extractor import Page  # noqa: E402
from verify import verify_numbers  # noqa: E402

PAGES = [Page(n, t) for n, t in sorted(REAL_PAGES.items())]
GOLDEN = (Path(__file__).parent / "fixtures" / "basic_semi_dossier_golden.md").read_text(encoding="utf-8")


def test_golden_passes():
    rep = verify_numbers(GOLDEN, PAGES, extra_allowed={"9971"})
    assert rep.ok, rep.summary()
    assert rep.checked >= 15
    print(f"✓ 金样例通过校验:{rep.checked} 个数字全部回查到原文({rep.ignored} 个页码/序号豁免)")


def test_fabrication_caught():
    # 注入三种典型编造:凭空数字、换算出的数字(111.5百万->1.115亿)、篡改的数字
    for bad, label in [
        ("公司2025年营收为888.8百万元【招股书 p.13】", "凭空数字"),
        ("经营现金净流出1.115亿元【招股书 p.22】", "私自换算"),
        ("前五大客户占比63.9%【招股书 p.17】", "篡改数字"),
    ]:
        rep = verify_numbers(GOLDEN + "\n" + bad, PAGES, extra_allowed={"9971"})
        assert not rep.ok, f"{label} 应被抓但通过了"
    print("✓ 编造闸门有效:凭空/换算/篡改三类假数字全部被抓")


def test_no_verdict_words():
    banned = ["涉嫌", "造假", "危险", "警惕", "割韭菜", "必然", "暴雷", "值得买", "不值得买"]
    for w in banned:
        assert w not in GOLDEN, f"金样例出现定性词:{w}"
    print("✓ 金样例无定性结论词(关注点=反差+问题)")


if __name__ == "__main__":
    test_golden_passes()
    test_fabrication_caught()
    test_no_verdict_words()
    print("\n拆解档案+校验器全部通过 ✅")
