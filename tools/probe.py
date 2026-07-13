"""接口探针 —— 在能访问交易所的环境里运行,确认真实字段名。

用途:上交所/港交所的列表数据走 JSON 接口。把浏览器 Network 面板里那个返回列表的
请求 URL 拷出来,喂给本脚本,它会用正确的头去打、剥 JSONP、打印真实字段名和一条样本。
拿到字段名后,回填到对应采集器的 map_record(上交所)或 PHIP 适配器里即可。

怎么拿那个 URL:
  浏览器打开列表页 -> F12 -> Network -> 刷新 -> 在请求里找返回项目列表的那个
  (上交所是 commonQuery.do;港交所申请版本索引看 appindex.html 加载的 XHR)
  -> 右键 Copy -> Copy link address,粘到下面命令里。

用法:
  python tools/probe.py "http://query.sse.com.cn/commonQuery.do?...&sqlId=...&..." \
      --referer http://www.sse.com.cn/
  python tools/probe.py "<港交所接口URL>" --referer https://www1.hkexnews.hk/
"""
from __future__ import annotations

import argparse
import json
import re
import sys

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def unwrap_jsonp(text: str) -> str:
    """jsonpCallbackXXX({...}) -> {...}(若本就是纯 JSON 则原样返回)。"""
    t = text.strip()
    if t.startswith("{") or t.startswith("["):
        return t
    m = re.search(r"[\(（](.*)[\)）]\s*;?\s*$", t, re.S)
    return m.group(1) if m else t


def find_record_list(data):
    """在返回结构里找那个'记录列表'(常挂在 result / pageHelp.data / data 下)。"""
    if isinstance(data, list):
        return data
    for path in (("result",), ("pageHelp", "data"), ("data",), ("records",)):
        cur = data
        ok = True
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and isinstance(cur, list) and cur:
            return cur
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="从 Network 面板拷来的接口 URL")
    ap.add_argument("--referer", default=None, help="需要的 Referer 头")
    args = ap.parse_args()

    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if args.referer:
        headers["Referer"] = args.referer

    print(f"→ 请求: {args.url[:120]}...")
    resp = requests.get(args.url, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding

    try:
        data = json.loads(unwrap_jsonp(resp.text))
    except json.JSONDecodeError:
        print("！返回不是 JSON/JSONP,原始前 500 字:")
        print(resp.text[:500])
        return 1

    print(f"顶层键: {list(data.keys()) if isinstance(data, dict) else '(list)'}")
    records = find_record_list(data)
    if not records:
        print("！没找到记录列表。完整返回前 800 字:")
        print(json.dumps(data, ensure_ascii=False)[:800])
        return 1

    print(f"记录数: {len(records)}")
    print(f"\n首条记录的字段名({len(records[0])} 个):")
    for k in records[0].keys():
        print(f"  - {k}")
    print("\n首条记录样本:")
    print(json.dumps(records[0], ensure_ascii=False, indent=2)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
