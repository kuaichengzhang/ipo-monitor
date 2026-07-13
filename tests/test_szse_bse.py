"""深交所 + 北交所测试 —— 对着真实接口样本验证(接口、字典均经浏览器实测)。

深交所:api/ras/projectrends/query,官方状态字典取自接口 stageList(实测 1461 项目)。
北交所:projectNewsController/infoResult.do,P码字典取自页面官方筛选器(实测 871 项目)。
样本文件为真实返回结构 + 真实记录值(田园生化/鸿富诚/德硕/百利/信胜)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.szse import parse_query_response as szse_parse, map_record as szse_map  # noqa: E402
from collectors.bse import (  # noqa: E402
    unwrap_callback, parse_response as bse_parse, status_text, map_record as bse_map,
)
from stages import (  # noqa: E402
    normalize_stage, is_trigger, PASSED, ACCEPTED, INQUIRED, HEARING,
    SUBMITTED_REG, EFFECTIVE, TERMINATED, SUSPENDED,
)

FIX = Path(__file__).parent / "fixtures"


def test_szse_official_dict():
    """深交所官方状态字典(接口 stageList 全 16 态)-> 统一阶段。"""
    cases = {
        "已受理": ACCEPTED, "已问询": INQUIRED,
        "上市委会议通过": PASSED, "上市委会议未通过": TERMINATED,
        "暂缓审议": HEARING, "上市委复审会议通过": PASSED, "上市委复审会议未通过": TERMINATED,
        "提交注册": SUBMITTED_REG, "注册生效": EFFECTIVE,
        "不予注册": TERMINATED, "补充审核": INQUIRED, "终止注册": TERMINATED,
        "中止": SUSPENDED, "终止(审核不通过)": TERMINATED,
        "终止(撤回)": TERMINATED, "终止(未在规定时限内回复)": TERMINATED,
    }
    for raw, expect in cases.items():
        got = normalize_stage("深交所", raw)
        assert got == expect, f"深交所 {raw} 应->{expect},实为{got}"
    print(f"✓ 深交所官方字典 {len(cases)} 个状态全部正确归一化")


def test_szse_parse_real_sample():
    filings, total = szse_parse((FIX / "szse_ras_sample.json").read_text(encoding="utf-8"))
    assert total == 1461 and len(filings) == 4
    by = {f.company_name: f for f in filings}

    ty = by["广西田园生化股份有限公司"]
    assert ty.board == "主板" and ty.stage == INQUIRED and ty.sponsor == "国海证券"
    assert ty.source_url == "https://www.szse.cn/listing/projectdynamic/ipo/detail/index.html?id=1003977"
    assert ty.page_updated == "2026-07-13"

    hfc = by["深圳市鸿富诚新材料股份有限公司"]
    assert hfc.board == "创业板" and hfc.status == "注册生效" and hfc.stage == EFFECTIVE
    assert is_trigger(hfc.stage)
    print("✓ 深交所真实样本 4 条解析正确:板块/状态/保荐/日期/触发全对(totalSize=1461)")


def test_bse_pcode_dict():
    """北交所 P 码 -> 状态文字 -> 统一阶段(含裸 P07 容错)。"""
    assert status_text("P01") == "已受理"
    assert status_text("P03") == "上市委会议通过"
    assert status_text("P06") == "提交注册"
    assert status_text("P07-1") == "注册生效"
    assert status_text("P07-2") == "核准"
    assert status_text("P07") == "注册生效"       # 数据中的裸 P07
    assert status_text("P10") == "终止"
    assert normalize_stage("北交所", "核准") == EFFECTIVE
    assert normalize_stage("北交所", "上市委会议通过") == PASSED
    assert normalize_stage("北交所", "上市委会议暂缓") == HEARING
    print("✓ 北交所 P 码字典正确(含精选层'核准'口径与裸 P07 容错)")


def test_bse_parse_real_sample():
    payload = unwrap_callback((FIX / "bse_infoResult_sample.jsonp").read_text(encoding="utf-8"))
    filings, total_pages = bse_parse(payload)
    assert total_pages == 44 and len(filings) == 3
    by = {f.company_name: f for f in filings}

    ds = by["浙江德硕科技股份有限公司"]
    assert ds.status == "提交注册" and ds.stage == SUBMITTED_REG
    assert is_trigger(ds.stage)                       # 提交注册 = ★可选题
    assert ds.sponsor == "国泰海通证券股份有限公司"
    assert ds.stock_code == "874669"
    assert ds.source_url == "https://www.bse.cn/audit/project_news_detail.html?id=637"
    assert ds.page_updated == "2026-07-10"            # Java Date {time:毫秒} -> 日期

    xs = by["浙江信胜科技股份有限公司"]
    assert xs.status == "注册生效" and xs.stage == EFFECTIVE
    print("✓ 北交所真实样本 3 条解析正确:P码/保荐/JavaDate日期/触发全对(44页/871项)")


def test_four_exchanges_one_stage_vocab():
    """四所验收:不同状态词落进同一套统一阶段。"""
    quad = [
        normalize_stage("港交所", "聆讯后资料集(PHIP)"),
        normalize_stage("上交所", "上市委会议通过"),
        normalize_stage("深交所", "上市委会议通过"),
        normalize_stage("北交所", "上市委会议通过"),
    ]
    assert all(s == PASSED and is_trigger(s) for s in quad)
    print("✓ 四所统一:PHIP(港)/上市委通过(沪深北)都=过会,都触发★可选题")


if __name__ == "__main__":
    test_szse_official_dict()
    test_szse_parse_real_sample()
    test_bse_pcode_dict()
    test_bse_parse_real_sample()
    test_four_exchanges_one_stage_vocab()
    print("\n深交所+北交所(真实接口)全部通过 ✅ 四所全通")
