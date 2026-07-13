"""看板 v2 测试:交互数据内嵌、首次收录标签、档案链接、审核页链接。"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.sse import parse_query_response
from collectors.hkex import parse_new_listing_info
from dashboard import generate_dashboard
from dossier import md_to_html

FIX = Path(__file__).parent / "fixtures"


def _all():
    sse = parse_query_response((FIX/"sse_soaquery_sample.jsonp").read_text(encoding="utf-8"))
    hk = parse_new_listing_info((FIX/"hkex_new_listing_sample.html").read_text(encoding="utf-8"), "主板", "https://x")
    return sse + hk


def test_first_run_label():
    fs = _all()
    html = generate_dashboard(fs, new_uids={f.uid for f in fs})
    assert "首次收录" in html and "今日新增" not in html
    html2 = generate_dashboard(fs, new_uids={fs[0].uid})
    assert "今日新增 1" in html2
    print("✓ 首次运行显示'首次收录',常规运行显示'今日新增'")


def test_embedded_data_and_controls():
    fs = _all()
    html = generate_dashboard(fs)
    assert 'id="q"' in html and 'id="pager"' in html and "只看 ★可选题" in html
    assert "交易所审核页" in html or "src" in html  # 卡片提供审核页链接字段
    # 内嵌数据可解析,含上交所与港交所
    data = html.split("const DATA = ",1)[1].split(";\n",1)[0]
    rows = json.loads(data)
    assert any(r["ex"]=="上交所" for r in rows) and any(r["ex"]=="港交所" for r in rows)
    assert all("src" in r for r in rows)
    print(f"✓ 搜索/筛选/分页控件齐全,内嵌 {len(rows)} 条数据可解析")


def test_dossier_button():
    fs = _all()
    name = fs[0].company_name
    html = generate_dashboard(fs, dossier_map={name: "data/dossiers/x.html"})
    assert "拆解档案" in html and "data/dossiers/x.html" in html
    print("✓ 有档案的公司,卡片出'拆解档案'按钮")


def test_md_to_html():
    h = md_to_html("# 标题\n\n> 引言\n\n## 二、赚不赚钱\n\n- 亏损 **3.347亿**【招股书 p.22】\n\n---")
    assert "<h1>标题</h1>" in h and "<h2>" in h and "<li>" in h
    assert "<strong>3.347亿</strong>" in h and "返回监控看板" in h
    print("✓ 档案 md->html 渲染正常,带返回看板链接")


def test_v3_pinyin_and_pager():
    """v3:拼音首字母进数据、真分页控件、URL状态。"""
    fs = _all()
    html = generate_dashboard(fs)
    data = html.split("const DATA = ",1)[1].split(";\n",1)[0]
    rows = json.loads(data)
    shengu = next(r for r in rows if "沈鼓" in r["name"])
    assert shengu["py"].startswith("sgjt"), f"拼音索引:{shengu['py']}"
    assert shengu["pys"] == "zjgs"  # 中金公司
    assert "pagerHtml" in html and "上一页" in html and "跳页" in html and "/页" in html
    assert "readState" in html and "history.replaceState" in html  # URL 状态
    assert "<mark>" in html or "mark {" in html                    # 高亮样式
    print("✓ v3:拼音首字母(沈鼓=sgjt/中金=zjgs)、页码条、每页数量、跳页、URL状态、高亮齐全")


if __name__ == "__main__":
    test_first_run_label()
    test_embedded_data_and_controls()
    test_dossier_button()
    test_md_to_html()
    test_v3_pinyin_and_pager()
    print("\n看板 v2/v3 全部通过 ✅")
