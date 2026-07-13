"""三所招股书直链解析器测试(对真实接口返回节选)。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from detail_apis_real import SSE_FILES, SZSE_DETAIL, BSE_DETAIL  # noqa: E402
from collectors.resolve import sse_pick, szse_pick, bse_pick  # noqa: E402


def test_sse_pick():
    url = sse_pick(SSE_FILES)   # session=None -> 不做HEAD,直接拼static
    assert url == "https://static.sse.com.cn/disclosure/announcement/c/202607/002239_20260707_M7F6.pdf"
    # 5份文件里只挑招股说明书(I0011),不误抓法律意见书/保荐书
    print("✓ 上交所:5份文件中精确挑出招股说明书(申报稿),static直链拼接正确")


def test_sse_prefers_later_stage():
    files = SSE_FILES + [{"fileTitle": "某公司招股说明书（注册稿）",
                          "filePath": "/disclosure/announcement/c/202608/x_reg.pdf",
                          "fileTypeMap": "I0013", "fileUpdTime": "20260801000000"}]
    assert sse_pick(files).endswith("x_reg.pdf")
    print("✓ 上交所:注册稿优先于申报稿(取审核最新版)")


def test_szse_pick():
    url = szse_pick(SZSE_DETAIL)
    assert url == "https://reportdocs.static.szse.cn/UpFiles/rasinfodisc1/202606/RAS_202606_301700C477277F838A4961846B5A047E2F655B.pdf"
    print("✓ 深交所:3版招股说明书取最新(2026-06-30),reportdocs直链正确,不误抓保荐书")


def test_bse_pick():
    url = bse_pick(BSE_DETAIL)
    assert url == "https://www.bse.cn/disclosure/2026/2026-07-10/1783695860_165591.pdf"
    print("✓ 北交所:递归分组结构中挑出招股说明书最新版(报会稿2026-07-10),bse.cn直链正确")


def test_no_match_returns_none():
    assert szse_pick({"disclosureMaterials": [{"matnm": "法律意见书", "dfpth": "/x.pdf", "ddt": "2026"}]}) is None
    assert bse_pick({"xxgkInfo": {}}) is None
    assert sse_pick([]) is None
    print("✓ 无招股说明书时返回 None(不猜、不拿别的文件顶替)")


if __name__ == "__main__":
    test_sse_pick()
    test_sse_prefers_later_stage()
    test_szse_pick()
    test_bse_pick()
    test_no_match_returns_none()
    print("\n三所直链解析器全部通过 ✅")
