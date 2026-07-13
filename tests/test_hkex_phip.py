"""港交所 AP&PHIP 采集器测试。

接口、字段经浏览器实测确认(appactive_app_sehk_c.json)。
样本 fixtures/hkex_appphip_sample.json 为真实返回(思卓、袁記食品,均为申请版本阶段)。
当前在审列表中暂无 hasPhip=true 的记录,故 PHIP 分支用一条构造记录(按真实 ls/ps 文档
结构 + 港交所 PHIP 文档命名「聆訊後資料集」)单独验证。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.hkex import map_app_record  # noqa: E402
from stages import ACCEPTED, PASSED, is_trigger  # noqa: E402
import json  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "hkex_appphip_sample.json"


def test_real_ap_records():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    filings = [map_app_record(r, "主板") for r in data["app"]]
    assert len(filings) == 2

    sizhuo = filings[0]
    assert sizhuo.company_name == "思卓基礎設施私募資本開放式基金公司"
    assert sizhuo.status == "申请版本" and sizhuo.stage == ACCEPTED
    assert not is_trigger(sizhuo.stage)          # 仅申请版本,未触发
    assert sizhuo.stock_code == "107796"          # id=文件夹号
    assert sizhuo.prospectus_url == "https://www1.hkexnews.hk/app/sehk/2025/107796/documents/sehk25101701816_c.pdf"
    assert sizhuo.phip_url is None
    assert sizhuo.page_updated == "2025-10-17"

    yuanji = filings[1]
    assert yuanji.company_name == "袁記食品集團股份有限公司"
    assert yuanji.prospectus_url.endswith("sehk26011200695_c.pdf")
    print("✓ 真实申请版本记录 2 条解析正确:公司名、阶段、文件夹号、申请版本PDF链接、日期")


def test_phip_trigger_branch():
    """hasPhip=true + 聆訊後資料集文档 -> 过会(PASSED,触发),phip_url 抽取正确。"""
    rec = {
        "id": 108888, "d": "05/07/2026", "a": "某硬科技股份有限公司", "hasPhip": True,
        "ls": [{"nF": "申請版本（第一次呈交）", "u1": "sehk/2026/108888/documents/sehk26010100001_c.pdf"}],
        "ps": [{"nF": "聆訊後資料集", "nS1": "全文檔案", "u1": "sehk/2026/108888/documents/sehk26070500123_c.pdf"}],
    }
    f = map_app_record(rec, "主板")
    assert f.status == "聆讯后资料集(PHIP)" and f.stage == PASSED
    assert is_trigger(f.stage)                     # 过会 = 可选题
    assert f.phip_url == "https://www1.hkexnews.hk/app/sehk/2026/108888/documents/sehk26070500123_c.pdf"
    assert f.prospectus_url == f.phip_url           # 有PHIP优先用PHIP
    print("✓ PHIP 分支:hasPhip -> 过会(触发),PHIP链接抽取正确,优先于申请版本")


if __name__ == "__main__":
    test_real_ap_records()
    test_phip_trigger_branch()
    print("\n港交所 AP&PHIP(真实接口)全部通过 ✅")
