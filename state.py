"""状态存储与去重。

把每次抓到的 Filing 按 uid 存进 data/state.json;重跑时:
- 新 uid  -> 记为「新增」,写入 first_seen
- 老 uid  -> 只更新 last_seen(及变化的字段)
这样每天跑一次,就能回答「今天谁递了表 / 谁状态变了」。
"""
from __future__ import annotations

import json
from pathlib import Path

from models import Filing, utc_now_iso


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def diff_and_update(self, filings: list[Filing]) -> dict[str, list[Filing]]:
        """返回 {'new': [...], 'changed': [...]},并就地更新状态。"""
        now = utc_now_iso()
        new: list[Filing] = []
        changed: list[Filing] = []

        for f in filings:
            rec = f.to_dict()
            uid = rec["uid"]
            if uid not in self._data:
                rec["first_seen"] = now
                rec["last_seen"] = now
                self._data[uid] = rec
                new.append(f)
            else:
                prev = self._data[uid]
                # 状态字段变化(如从"上市公告"到"招股")算 changed
                if prev.get("status") != rec.get("status"):
                    changed.append(f)
                prev["last_seen"] = now
                prev["status"] = rec["status"]
                for k in ("prospectus_url", "announcement_url", "allotment_url", "phip_url"):
                    if rec.get(k):
                        prev[k] = rec[k]
        return {"new": new, "changed": changed}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def all_records(self) -> list[dict]:
        return list(self._data.values())
