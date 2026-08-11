"""回收站服务：记录被剔除/删除的账号（含时间、上游返回原因、来源）。

解决：账号被自动剔除（失效/停用/配额耗尽）或手动删除后，无任何痕迹可查。
本模块将删除动作记入回收站，支持：
- 记录：email / access_token / 删除时间 / 状态 / 上游返回原因 / 来源
- 查询：列表 + 统计（按状态分类、按天分布）
- 清空 / 恢复（恢复：重新加入号池，供手动复活场景）

存储：data/trash.json（原子写 + 线程安全），与账号库同目录便于备份。
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from services.storage.json_storage import _atomic_write_text

TRASH_FILE = DATA_DIR / "trash.json"

# 回收站单条上限（防无限增长，超限裁最旧）
_MAX_ENTRIES = 2000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class TrashService:
    """账号回收站（线程安全，原子落盘）。"""

    def __init__(self, path: Path = TRASH_FILE, max_entries: int = _MAX_ENTRIES) -> None:
        self._path = path
        self._max_entries = max(1, int(max_entries))
        self._lock = threading.RLock()
        self._entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._entries = [e for e in data if isinstance(e, dict)]
        except (json.JSONDecodeError, OSError):
            self._entries = []

    def _save(self) -> None:
        # 裁剪最旧条目（按 appended_at 升序，保留最新）
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]
        _atomic_write_text(self._path, json.dumps(self._entries, ensure_ascii=False, indent=2) + "\n")

    def add(
        self,
        *,
        email: str = "",
        access_token: str = "",
        status: str = "",
        reason: str = "",
        source: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        """记录一条被剔除/删除的账号。"""
        entry = {
            "email": str(email or "").strip(),
            "access_token": str(access_token or "").strip(),
            "status": str(status or "").strip(),
            "reason": str(reason or "").strip(),
            "source": str(source or "").strip(),
            "removed_at": _now_iso(),
            "detail": dict(detail) if detail else {},
        }
        with self._lock:
            self._entries.append(entry)
            self._save()

    def add_from_account(self, account: dict[str, Any] | None, *, reason: str = "", source: str = "") -> None:
        """从账号字典构造回收站条目（保留 email/token/状态）。"""
        if not account:
            return
        self.add(
            email=str(account.get("email") or "").strip(),
            access_token=str(account.get("access_token") or "").strip(),
            status=str(account.get("status") or "").strip(),
            reason=reason,
            source=source,
            detail={
                "last_refresh_error": str(account.get("last_refresh_error") or ""),
                "last_token_refresh_error": str(account.get("last_token_refresh_error") or ""),
                "invalid_count": int(account.get("invalid_count") or 0),
            },
        )

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        """最近 N 条回收记录（新→旧）。"""
        with self._lock:
            return list(reversed(self._entries[-limit:]))

    def stats(self, top_reasons: int = 8) -> dict[str, Any]:
        """回收站统计：总数 + 状态分布 + 按天分布 + 原因分布。

        新增图表友好字段（向后兼容，原字段保留）：
        - ``by_reason_top``: 上游原因 Top N 分布（数组，按数量降序），供条形图
        - ``trend``: 按天剔除数趋势（数组，时间升序），供趋势图
        """
        with self._lock:
            total = len(self._entries)
            by_status: dict[str, int] = {}
            by_day: dict[str, int] = {}
            by_reason: dict[str, int] = {}
            for e in self._entries:
                status = str(e.get("status") or "未知") or "未知"
                by_status[status] = by_status.get(status, 0) + 1
                day = str(e.get("removed_at") or "")[:10] or "未知"
                by_day[day] = by_day.get(day, 0) + 1
                reason = str(e.get("reason") or "未知")[:40] or "未知"
                by_reason[reason] = by_reason.get(reason, 0) + 1
            reasons_sorted = sorted(by_reason.items(), key=lambda kv: -kv[1])
            top_n = max(1, min(100, int(top_reasons)))
            return {
                "total": total,
                "by_status": by_status,
                "by_day": dict(sorted(by_day.items(), reverse=True)),
                "by_reason": dict(reasons_sorted),
                "by_reason_top": [
                    {"reason": reason, "count": count}
                    for reason, count in reasons_sorted[:top_n]
                ],
                "trend": [
                    {"day": day, "count": by_day[day]}
                    for day in sorted(by_day.keys())
                ],
            }

    def clear(self) -> int:
        """清空回收站，返回清除条数。"""
        with self._lock:
            count = len(self._entries)
            self._entries = []
            self._save()
            return count

    def restore(self, emails: list[str]) -> dict[str, Any]:
        """从回收站恢复指定 email 的账号（删除回收站记录）。

        注意：恢复的是「记录」，实际号池重新入库需另行导入。此处仅
        从回收站移除记录，避免用户误以为号还在。
        """
        target = {str(e or "").strip().lower() for e in emails if str(e or "").strip()}
        if not target:
            return {"restored": 0, "total": 0}
        with self._lock:
            kept: list[dict[str, Any]] = []
            restored = 0
            for e in self._entries:
                if str(e.get("email") or "").strip().lower() in target:
                    restored += 1
                else:
                    kept.append(e)
            self._entries = kept
            self._save()
            return {"restored": restored, "total": len(self._entries)}


trash_service = TrashService()
