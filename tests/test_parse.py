"""对着真实数据样本测试解析与去重逻辑。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.hkex import parse_new_listing_info  # noqa: E402
from models import parse_hkex_markers, Filing  # noqa: E402
from state import StateStore  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "hkex_new_listing_sample.html"
SRC = "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=zh-cn"


def test_markers():
    name, mk = parse_hkex_markers("MOMENTA GLOBAL LIMITED - W")
    assert name == "MOMENTA GLOBAL LIMITED"
    assert mk == ["同股不同权(WVR)"]
    # 无标记
    name2, mk2 = parse_hkex_markers("Luxshare Precision Industry Co., Ltd.")
    assert mk2 == []
    # 多标记
    _, mk3 = parse_hkex_markers("SOME BIOTECH CO - B - W")
    assert mk3 == ["未盈利生物科技(18A)", "同股不同权(WVR)"]
    print("✓ 标记位解析")


def test_parse():
    html = FIXTURE.read_text(encoding="utf-8")
    filings = parse_new_listing_info(html, "主板", SRC)

    assert len(filings) == 7, f"应解析出 7 家,实得 {len(filings)}"

    by_code = {f.stock_code: f for f in filings}

    rokae = by_code["3752"]
    assert rokae.company_name == "Rokae (Shandong) Robotics Group Inc."
    assert rokae.status == "招股(已刊发招股章程)"
    assert rokae.prospectus_url.endswith("2026063000033.pdf")
    assert rokae.exchange == "港交所" and rokae.board == "主板"
    assert rokae.page_updated == "07 Jul 2026"

    momenta = by_code["6880"]
    assert momenta.company_name == "MOMENTA GLOBAL LIMITED"
    assert momenta.markers == ["同股不同权(WVR)"]

    # 只有配发结果、无招股书的那条,状态应为「已配发结果」
    trt = by_code["2667"]
    assert trt.prospectus_url is None
    assert trt.status == "已配发结果"
    assert trt.allotment_url.endswith("2026070602117.pdf")

    print(f"✓ 解析 {len(filings)} 家,字段/状态/标记/链接全部对上")


def test_dedup_and_change(tmp_path=Path("/tmp")):
    """模拟两天:第一天 7 家全新增;第二天其中一家状态推进,应报 changed。"""
    html = FIXTURE.read_text(encoding="utf-8")
    day1 = parse_new_listing_info(html, "主板", SRC)

    state_file = Path("/tmp/_test_state.json")
    if state_file.exists():
        state_file.unlink()

    store = StateStore(state_file)
    d1 = store.diff_and_update(day1)
    store.save()
    assert len(d1["new"]) == 7 and len(d1["changed"]) == 0
    print(f"✓ 第一天:{len(d1['new'])} 家全部记为新增")

    # 第二天:同样的数据重跑 -> 应无新增、无变化
    store2 = StateStore(state_file)
    d2 = store2.diff_and_update(parse_new_listing_info(html, "主板", SRC))
    store2.save()
    assert len(d2["new"]) == 0 and len(d2["changed"]) == 0
    print("✓ 第二天重跑同数据:0 新增、0 变化(去重生效)")

    # 第三天:2667 从"配发"推进(手动改一条状态模拟)
    store3 = StateStore(state_file)
    advanced = parse_new_listing_info(html, "主板", SRC)
    for f in advanced:
        if f.stock_code == "2667":
            f.status = "上市首日"
    d3 = store3.diff_and_update(advanced)
    assert len(d3["changed"]) == 1 and d3["changed"][0].stock_code == "2667"
    print("✓ 第三天:检测到 2667 状态变化 -> 上市首日")

    state_file.unlink()


if __name__ == "__main__":
    test_markers()
    test_parse()
    test_dedup_and_change()
    print("\n全部通过 ✅")
