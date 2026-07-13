"""上交所采集器测试 —— 对着真实接口样本(思朗/中导/沈鼓)验证。

接口、字段、状态码均经浏览器 Network 实测确认(commonSoaQuery.do / sqlId=SH_XM_LB)。
样本文件 fixtures/sse_soaquery_sample.jsonp 为真实返回结构 + 真实记录值。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors import sse  # noqa: E402
from collectors.sse import map_record, parse_query_response, response_total  # noqa: E402
from stages import (  # noqa: E402
    normalize_stage, is_trigger, PASSED, ACCEPTED, EFFECTIVE,
    SUBMITTED_REG, TERMINATED, INQUIRED, HEARING, SUSPENDED,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sse_soaquery_sample.jsonp"


def test_status_code_map():
    """currStatus 数字码 -> 统一阶段(码值经页面状态筛选器实测)。"""
    expect = {
        1: ACCEPTED, 2: INQUIRED, 3: HEARING, 9: HEARING,
        4: SUBMITTED_REG, 5: EFFECTIVE, 7: SUSPENDED, 8: TERMINATED, 10: INQUIRED,
    }
    for code, stage in expect.items():
        f = map_record({"currStatus": code, "stockAuditName": "测试", "issueMarketType": 1})
        assert f.stage == stage, f"currStatus={code} 应 -> {stage},实为 {f.stage}"
    print(f"✓ {len(expect)} 个 currStatus 数字码全部正确映射到统一阶段")


def test_parse_real_sample():
    """解析真实 JSONP 样本(思朗/中导/沈鼓)。"""
    text = FIXTURE.read_text(encoding="utf-8")
    assert response_total(text) == 1281
    filings = parse_query_response(text)
    assert len(filings) == 3

    by_name = {f.company_name: f for f in filings}

    # 思朗:名字后缀"科创板IPO项目"应被清洗掉
    silang = by_name["上海思朗科技股份有限公司"]
    assert silang.board == "科创板"
    assert silang.status == "已受理" and silang.stage == ACCEPTED
    assert silang.sponsor == "国泰海通"          # 只取 type==1 的保荐机构
    assert silang.stock_code == "2239"
    assert silang.page_updated == "2026-07-07"

    # 沈鼓:提交注册 = 过会后 = 触发选题
    shengu = by_name["沈鼓集团股份有限公司"]
    assert shengu.board == "主板"
    assert shengu.status == "提交注册" and shengu.stage == SUBMITTED_REG
    assert shengu.sponsor == "中金公司"
    assert is_trigger(shengu.stage)

    # 中导:已问询
    zhongdao = by_name["中导光电设备股份有限公司"]
    assert zhongdao.stage == INQUIRED and not is_trigger(zhongdao.stage)

    print("✓ 真实样本 3 条解析正确:名字清洗、板块、状态、保荐机构、触发判定全对")


def test_committee_refinement():
    """上市委审议 + 会议结果=通过 -> 过会(PASSED, 触发)。"""
    passed = map_record({"currStatus": 3, "commitiResult": "通过", "stockAuditName": "甲", "issueMarketType": 1})
    assert passed.stage == PASSED and is_trigger(passed.stage)
    failed = map_record({"currStatus": 3, "commitiResult": "未通过", "stockAuditName": "乙", "issueMarketType": 1})
    assert failed.stage == TERMINATED
    print("✓ 上市委会议结果细化:通过->过会(触发),未通过->终止")


def test_sponsor_picks_type1():
    """中介数组里只认 type==1 的保荐机构。"""
    f = map_record({"currStatus": 1, "stockAuditName": "丙", "issueMarketType": 1,
                    "intermediary": [{"i_intermediaryType": 5, "i_intermediaryAbbrName": "会计所"},
                                     {"i_intermediaryType": 1, "i_intermediaryAbbrName": "某券商"}]})
    assert f.sponsor == "某券商"
    print("✓ 保荐机构提取:跳过会计所,取 type==1 券商")


def test_cross_exchange_unification():
    """港交所与上交所不同状态词落进同一套统一阶段。"""
    assert normalize_stage("港交所", "招股(已刊发招股章程)") == EFFECTIVE
    assert map_record({"currStatus": 5, "stockAuditName": "x", "issueMarketType": 1}).stage == EFFECTIVE
    assert normalize_stage("港交所", "聆讯后资料集(PHIP)") == PASSED
    assert map_record({"currStatus": 4, "stockAuditName": "y", "issueMarketType": 1}).stage == SUBMITTED_REG
    print("✓ 跨所统一:两所记录落进同一阶段词汇")


if __name__ == "__main__":
    test_status_code_map()
    test_parse_real_sample()
    test_committee_refinement()
    test_sponsor_picks_type1()
    test_cross_exchange_unification()
    print("\n上交所(真实接口)全部通过 ✅")
