"""采集器基类。

设计目标(对应规格书「四适配器、一接口」):
每个交易所/数据源实现一个 Collector 子类,只需提供 collect() -> list[Filing]。
上层 run.py 不关心某个源是 HTML 表还是 JSON 接口。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import requests

from models import Filing

# 港交所站点对 UA 较敏感,给一个正常浏览器 UA
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class BaseCollector(ABC):
    name: str = "base"

    def __init__(self, timeout: int = 30, session: requests.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def get(self, url: str) -> str:
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        return resp.text

    @abstractmethod
    def collect(self) -> list[Filing]:
        """抓取并返回结构化记录。子类实现。"""
        raise NotImplementedError
