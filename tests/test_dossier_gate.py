"""档案校验闸门测试 —— 核心:模型说谎/越线时,闸门必须拦住。

用一个"作弊假模型"注入 generate_dossier:它会编数字、下判断、张冠李戴页码。
闸门若放过任何一条,即为失败。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from basic_semi_en_excerpts import REAL_PAGES  # noqa: E402
from extractor import Page  # noqa: E402
from dossier import gate, generate_dossier, build_prompt, MISSING  # noqa: E402

PAGES = [Page(n, t) for n, t in sorted(REAL_PAGES.items())]


def test_gate_passes_honest_lines():
    """诚实的句子(数字+正确页码)应通过。"""
    md = "前五大客户收入占比为 46.4%、63.1% 及 40.4%【招股书 p.17】。\n2025 年经营活动现金流净流出 RMB111.5 million【招股书 p.22】。"
    cleaned, r = gate(md, PAGES)
    assert r.clean and MISSING not in cleaned
    assert r.passed_sentences == 2
    print("✓ 诚实句子(真数字+真页码)全部放行")


def test_gate_blocks_fabricated_number():
    """编造的数字(87.9% 不在任何页)必须拦截。"""
    md = "公司市占率高达 87.9%【招股书 p.17】。"
    cleaned, r = gate(md, PAGES)
    assert not r.clean and len(r.rejected_bad_cite) == 1
    assert MISSING in cleaned and "已拦截" in cleaned   # 拦截提示引用被拒数字供人工复核,属预期
    print("✓ 编造数字被拦:87.9% 在 p.17 原文对不上 -> 打回标待核")


def test_gate_blocks_uncited_number():
    """有数字无出处必须拦截。"""
    md = "公司去年亏了 3.2 亿元。"
    cleaned, r = gate(md, PAGES)
    assert len(r.rejected_no_cite) == 1 and MISSING in cleaned
    print("✓ 无出处数字被拦")


def test_gate_blocks_verdict_language():
    """定性词必须拦截,即使数字和页码都对。"""
    md = "客户占比 63.1%【招股书 p.17】,涉嫌财务操纵,投资者需警惕。"
    cleaned, r = gate(md, PAGES)
    assert len(r.rejected_banned) == 1 and MISSING in cleaned
    print("✓ 定性措辞被拦(数字对也不放行)")


def test_gate_blocks_wrong_page_cite():
    """张冠李戴:真数字挂错页码,必须拦截。63.1% 在 p.17,不在 p.24。"""
    md = "前五大客户占比曾达 63.1%【招股书 p.24】。"
    cleaned, r = gate(md, PAGES)
    assert len(r.rejected_bad_cite) == 1
    print("✓ 页码张冠李戴被拦(数字真、页码错 -> 打回)")


def test_full_pipeline_with_cheating_llm():
    """端到端:作弊假模型输出混合稿,闸门只放行干净句。"""
    def cheating_llm(prompt):
        return "\n".join([
            "## 二、赚不赚钱",
            "2025 年经营活动现金流净流出 RMB111.5 million【招股书 p.22】。",   # 诚实
            "公司实际隐藏利润 5.8 亿元【招股书 p.22】。",                        # 编造
            "这家公司造假迹象明显。",                                            # 定性
            "前五大客户占比 63.1%【招股书 p.17】。",                             # 诚实
        ])
    doc, r = generate_dossier("测试公司", "测试", PAGES, llm=cheating_llm)
    assert "111.5" in doc and "63.1" in doc
    assert "隐藏利润" not in doc
    assert "造假迹象明显" not in doc
    assert len(r.rejected_bad_cite) == 1 and len(r.rejected_banned) == 1
    assert "机器生成底稿" in doc and "校验闸门" in doc
    print("✓ 端到端:作弊模型的编造句/定性句全被拦,诚实句放行,底稿标识齐全")


def test_prompt_contains_rules_and_pages():
    p = build_prompt("某公司", PAGES)
    assert "铁律" in p and "[p.17]" in p and "46.4%" in p
    assert "不许写" in p and "原文照录" in p
    print("✓ prompt 含铁律与逐页原文")


if __name__ == "__main__":
    test_gate_passes_honest_lines()
    test_gate_blocks_fabricated_number()
    test_gate_blocks_uncited_number()
    test_gate_blocks_verdict_language()
    test_gate_blocks_wrong_page_cite()
    test_full_pipeline_with_cheating_llm()
    test_prompt_contains_rules_and_pages()
    print("\n校验闸门全部通过 ✅ —— 模型说谎也出不了稿")
