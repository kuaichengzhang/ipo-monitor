"""申万行业分类 enrichment —— 按股票代码判定是否属申万医药生物(医疗健康)。

权威底表方案(规避 GitHub Actions 上东方财富限流):
  - 仓库内置 collectors/sw_medical_static.json: 申万医药生物 6 个二级板块全部
    成分股(code -> 申万二级, 共 509 只, 其中 A 股 482 只), 由 gen_sw_static.py 生成并随代码提交。
  - SWMedicalCache 以该静态底表为权威: 运行时 100% 可靠, 不因网络限流而失效。
  - data/sw_medical.json 仅作为"增量补充缓存": best-effort 实时拉取发现的新代码会写入这里,
    叠加在静态底表之上(日常几乎用不到, 仅用于未来新上市医药股的自动补充)。

判定逻辑(run.py 调用):
  - A 股 6 位代码(沪深, 非北交所)命中底表 -> 医疗健康 + 申万二级子行业
  - A 股代码未命中(申万权威)        -> 非医疗, 不标记
  - 北交所 / 港交所 / 代码缺失       -> 公司名关键词兜底(申万不覆盖)

申万医药生物 6 个二级板块 -> 东方财富板块代码(BKxxxx):
        化学制药 BK0465 / 生物制品 BK1044 / 医疗器械 BK1041 /
        医疗服务 BK0727 / 中药Ⅱ BK1040 / 医药商业 BK1042
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

# 权威静态底表(随代码提交, 始终可用, 不受网络限流影响)
STATIC_PATH = Path(__file__).parent / "sw_medical_static.json"


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


def _load_static(path: Path) -> dict[str, str]:
    """加载权威静态底表: code -> 申万二级。失败返回空(此时 run.py 会回退关键词)。"""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        sub = d.get("sub") or {}
        if isinstance(sub, dict) and sub:
            return {str(k): str(v) for k, v in sub.items()}
    except Exception:
        pass
    return {}


class SWMedicalCache:
    """申万医药生物 code -> 二级行业 映射。

    权威底表 = 内置静态 JSON(始终可用);
    增量缓存 = data/sw_medical.json(仅 best-effort 实时补充, 日常为空)。
    """

    def __init__(self, path: Path, static_path: Path | None = None,
                 timeout: int = 15, session: requests.Session | None = None,
                 refresh_days: int = REFRESH_DAYS):
        self.path = Path(path)
        self.static_path = Path(static_path) if static_path else STATIC_PATH
        self.timeout = timeout
        self.refresh_days = refresh_days
        self.session = session or requests.Session()

        # 权威底表(随代码提交, 不受网络影响)
        self._static: dict[str, str] = _load_static(self.static_path)
        # 增量缓存(运行时 best-effort 补充)
        self._extra: dict[str, str] = {}
        self._load_extra()

        # best-effort 实时补充: 仅当增量缓存缺失/过期时尝试(限流时直接失败, 不阻塞)
        if not self._extra:
            try:
                self._refresh()
            except Exception:
                pass
            self._save_extra()

    # —— 持久化(仅增量缓存) ——
    def _load_extra(self) -> None:
        try:
            if not self.path.exists():
                return
            d = json.loads(self.path.read_text(encoding="utf-8"))
            sub = d.get("sub") or {}
            if isinstance(sub, dict):
                self._extra = {str(k): str(v) for k, v in sub.items()}
        except Exception:
            self._extra = {}

    def _save_extra(self) -> None:
        try:
            if not self._extra:
                return  # 没有新增, 不写文件(避免覆盖/刷提交)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"updated": date.today().strftime("%Y-%m-%d"),
                       "note": "增量补充(权威底表见 collectors/sw_medical_static.json)",
                       "sub": self._extra}
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except Exception:
            pass

    # —— best-effort 实时补充(限流时基本无效, 静默失败) ——
    def _refresh(self) -> None:
        for sub_name, bk in SW_BOARDS.items():
            codes = self._fetch_board(bk)
            added = 0
            for c in codes:
                if c not in self._static and c not in self._extra:
                    self._extra[c] = sub_name
                    added += 1
            print(f"  [申万增量] {sub_name}({bk}): 新发现 {added} 只")
        self._fetched_extra = True

    def _fetch_board(self, bk: str) -> list[str]:
        codes: list[str] = []
        for page in range(1, 11):
            batch = self._fetch_page(bk, page)
            if batch is None:
                break
            codes.extend(batch)
            if len(batch) < 100:
                break
            time.sleep(0.2)
        return codes

    def _fetch_page(self, bk: str, page: int) -> list[str] | None:
        for host in SW_HOSTS:
            try:
                r = self.session.get(
                    SW_LIST_URL.replace("push2.eastmoney.com", host),
                    params={"pn": str(page), "pz": "100",
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
        """映射是否可用(权威底表非空即可用; 若底表缺失才回退关键词)。"""
        return bool(self._static) or bool(self._extra)

    def is_medical(self, code: str) -> bool:
        c = str(code).strip()
        return c in self._static or c in self._extra

    def get_sub(self, code: str) -> str:
        c = str(code).strip()
        return normalize_sub(self._extra.get(c) or self._static.get(c, ""))

    # —— 对外接口 ——
    def save(self) -> None:
        """持久化增量补充缓存(权威静态底表不写此处)。"""
        self._save_extra()

    def total(self) -> int:
        """当前可用映射总数(权威底表 + 增量缓存)。"""
        return len(self._static) + len(self._extra)
