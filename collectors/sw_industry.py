"""申万行业分类 enrichment —— 按股票代码查东方财富 push2 取申万二级行业。

判据:
  - A 股财报(沪深北, 6 位代码): 调东方财富 qt/stock/get 取 f127 (申万二级行业)
  - f127 ∈ {化学制药, 生物制品, 医疗器械, 医疗服务, 中药(Ⅱ), 医药商业}
        -> 一级行业=医药生物 -> 标 "医疗健康"
  - 命中但非医疗(如 白酒Ⅱ/银行) -> 不标记(industry 保持空)
  - 查询失败 / 北交所(无申万分类, f127="") -> 回退到 industry.classify_industry 关键词兜底
  - 港交所(5 位代码) 申万覆盖不到 -> 保留原 markers/关键词逻辑

性能与鲁棒性:
  - 按股票代码缓存到 data/sw_industry_cache.json (code -> 申万二级), 跨运行复用
  - 同一运行内重复代码只查一次; 日常仅有新增代码触发真实请求
  - 瞬时网络失败(无 data) 不写入缓存, 下次运行重试; 北交所 f127="" 属正常, 会缓存
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

# 申万医药生物 6 个二级行业 (2021 版)。值统一映射到看板子行业标签。
SW_MEDICAL_SUBS: dict[str, str] = {
    "化学制药": "化学制药",
    "生物制品": "生物制品",
    "医疗器械": "医疗器械",
    "医疗服务": "医疗服务",
    "医药商业": "医药商业",
    # 中药在 2021 版写作 "中药Ⅱ"
    "中药Ⅱ": "中药",
    "中药": "中药",
}

SW_URL = "https://push2.eastmoney.com/api/qt/stock/get"
SW_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}


def _secid(code: str) -> str | None:
    """6 位 A 股代码 -> 东方财富 secid。上交所(6/9 开头)=1, 其余(深/北)=0。

    实测: 恒瑞医药 1.600276 OK; 森萱医药(北交所) 0.830946 OK, 1.830946 无数据。
    """
    code = str(code).strip()
    if len(code) != 6 or not code.isdigit():
        return None
    # 上交所(6/9 开头, 含 900xxx 沪市 B 股)=1; 其余(深市 0/3、北交所 8/4/92)=0
    # 注: 920xxx 为北交所, 虽以 9 开头仍属北交所 -> market 0
    market = "1" if (code[0] == "6" or (code[0] == "9" and not code.startswith("92"))) else "0"
    return f"{market}.{code}"


def is_sw_medical_sub(sub: str) -> bool:
    """申万二级行业是否为医药生物(医疗健康)。"""
    return sub in SW_MEDICAL_SUBS


def normalize_sub(sub: str) -> str:
    """申万二级名 -> 系统统一子行业标签。"""
    return SW_MEDICAL_SUBS.get(sub, sub)


class SWIndustryCache:
    """股票代码 -> 申万二级行业 缓存, 跨运行持久化到 data/ 下。"""

    def __init__(self, path: Path, timeout: int = 15,
                 session: requests.Session | None = None, delay: float = 0.12):
        self.path = Path(path)
        self.timeout = timeout
        self.delay = delay
        self.session = session or requests.Session()
        self._map: dict[str, str] = {}
        self.hit = 0      # 缓存命中
        self.miss = 0     # 真实查询
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._map = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._map = {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._map, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get_sub(self, code: str) -> str:
        """返回申万二级行业名(如 "化学制药"), 查不到/失败返回 ""。"""
        code = str(code).strip()
        if code in self._map:
            self.hit += 1
            return self._map[code]
        self.miss += 1
        sub, ok = self._fetch(code)
        if ok:
            self._map[code] = sub  # 仅持久化可靠结果(北交所 f127="" 也缓存)
        return sub

    def _fetch(self, code: str) -> tuple[str, bool]:
        """返回 (申万二级行业, 是否可靠结果)。

        - 瞬时网络失败 / data 为空 -> ("", False) 不缓存, 下次重试
        - 北交所等无申万分类(data 存在但 f127="") -> ("", True) 缓存空串
        """
        secid = _secid(code)
        if not secid:
            return ("", True)
        for attempt in range(3):
            try:
                r = self.session.get(
                    SW_URL,
                    params={"secid": secid, "fields": "f57,f127"},
                    headers=SW_HEADERS,
                    timeout=self.timeout,
                )
                r.raise_for_status()
                j = r.json()
                data = (j or {}).get("data")
                if not data:
                    # 无数据: 视为不可靠(可能为瞬时失败), 不缓存
                    return ("", False)
                sub = str(data.get("f127", "") or "").strip()
                return (sub, True)
            except Exception:
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        return ("", False)
