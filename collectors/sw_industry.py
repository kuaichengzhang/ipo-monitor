"""申万行业分类 enrichment —— 按股票代码判定是否属申万医药生物(医疗健康)。

核心思路(相比逐股查 f127 更稳):
  - 东方财富 push2 的 申万行业板块里, 医药生物(一级 BK1216) 下含 6 个二级板块:
        化学制药 BK0465 / 生物制品 BK1044 / 医疗器械 BK1041 /
        医疗服务 BK0727 / 中药Ⅱ BK1040 / 医药商业 BK1042
  - 一次性拉取这 6 个板块的全部成分股(各 ≤160 只, 共 ~480 只 A 股),
    构建 code -> 申万二级 映射, 按周缓存到 data/sw_medical.json
  - 报告判定: A 股 6 位代码命中映射 -> 医疗健康 + 申万二级子行业
            未命中(板块权威) -> 非医疗, 不标记
            北交所 / 港交所 / 代码缺失 -> 公司名关键词兜底(申万不覆盖)
  - 若缓存为空且实时拉取也失败(东方财富限流) -> 整体回退关键词兜底

为什么用板块成分股而非逐股 f127:
  - 逐股查 f127 在一次运行中要对 ~48 只股票各发一次请求,
    东方财富会对 GitHub Actions 出口 IP 突发限流, 导致 ~90% 请求返回空, 几乎全回退关键词
  - 板块成分股只需 6 次请求(按周缓存, 日常 0 次), 既稳又全(覆盖整张申万医药生物名单)
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path

import requests

# 申万医药生物 6 个二级板块 -> 东方财富板块代码(BKxxxx)
SW_BOARDS: dict[str, str] = {
    "化学制药": "BK0465",
    "生物制品": "BK1044",
    "医疗器械": "BK1041",
    "医疗服务": "BK0727",
    "中药Ⅱ": "BK1040",   # 2021 版写作 "中药Ⅱ"
    "医药商业": "BK1042",
}

# 子行业名 -> 看板统一标签(中药Ⅱ -> 中药)
SW_SUB_NORMALIZE: dict[str, str] = {
    "中药Ⅱ": "中药",
}

SW_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
# 多 host 轮询, 规避单点限流
SW_HOSTS = [
    "push2.eastmoney.com",
    "21.push2.eastmoney.com",
    "23.push2.eastmoney.com",
]
SW_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}
REFRESH_DAYS = 7


def _is_ashare(code: str) -> bool:
    """6 位 A 股代码(沪深, 非北交所)。北交所(8/4/92 开头)不属申万 A 股板块。"""
    code = str(code).strip()
    if len(code) != 6 or not code.isdigit():
        return False
    if code.startswith("92"):
        return False  # 北交所 92 开头(A 股板块不含)
    return code[0] in "0369"


def normalize_sub(sub: str) -> str:
    """申万二级名 -> 看板统一标签。"""
    return SW_SUB_NORMALIZE.get(sub, sub)


class SWMedicalCache:
    """申万医药生物 code -> 二级行业 映射, 按周缓存到 data/。"""

    def __init__(self, path: Path, timeout: int = 15,
                 session: requests.Session | None = None, refresh_days: int = REFRESH_DAYS):
        self.path = Path(path)
        self.timeout = timeout
        self.refresh_days = refresh_days
        self.session = session or requests.Session()
        self._map: dict[str, str] = {}   # code -> 申万二级
        self._fetched = False                  # 本次是否成功从网络拉取
        self._load()
        if not self._map:
            # 缓存缺失/过期/为空 -> 实时拉取一次
            self._fetch_all()
            self.save()

    # —— 持久化 ——
    def _load(self) -> None:
        try:
            if not self.path.exists():
                return
            d = json.loads(self.path.read_text(encoding="utf-8"))
            updated = d.get("updated", "")
            if updated:
                age = (date.today() - datetime.strptime(updated, "%Y-%m-%d").date()).days
                if age > self.refresh_days:
                    return  # 过期, 触发重拉
            sub = d.get("sub") or {}
            if isinstance(sub, dict) and sub:
                self._map = {str(k): str(v) for k, v in sub.items()}
        except Exception:
            self._map = {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"updated": date.today().strftime("%Y-%m-%d"), "sub": self._map}
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        except Exception:
            pass

    # —— 网络拉取 ——
    def _fetch_all(self) -> None:
        for sub_name, bk in SW_BOARDS.items():
            codes = self._fetch_board(bk)
            for c in codes:
                self._map[c] = sub_name
            print(f"  [申万] {sub_name}({bk}): {len(codes)} 只")
        self._fetched = True

    def _fetch_board(self, bk: str) -> list[str]:
        """拉取单个板块全部成分股代码(自动翻页 + 多 host 轮询)。"""
        codes: list[str] = []
        for page in range(1, 11):
            batch = self._fetch_page(bk, page)
            if batch is None:
                break  # 网络全失败
            codes.extend(batch)
            if len(batch) < 500:
                break  # 末页
            time.sleep(0.2)
        return codes

    def _fetch_page(self, bk: str, page: int) -> list[str] | None:
        for host in SW_HOSTS:
            try:
                r = self.session.get(
                    SW_LIST_URL.replace("push2.eastmoney.com", host),
                    params={"pn": str(page), "pz": "500",
                             "fs": f"b:{bk}", "fields": "f12"},
                    headers=SW_HEADERS,
                    timeout=self.timeout,
                )
                r.raise_for_status()
                j = r.json()
                data = (j or {}).get("data")
                if not data or not data.get("diff"):
                    return [] if data is not None else None
                return [str(it["f12"]).strip()
                        for it in data["diff"].values()
                        if it.get("f12")]
            except Exception:
                continue
        return None

    # —— 查询接口 ——
    def available(self) -> bool:
        """映射是否可用(非空)。为空说明缓存缺失且实时拉取也失败。"""
        return bool(self._map)

    def is_medical(self, code: str) -> bool:
        return str(code).strip() in self._map

    def get_sub(self, code: str) -> str:
        return normalize_sub(self._map.get(str(code).strip(), ""))
