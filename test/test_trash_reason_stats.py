"""回收站聚合统计（原因 Top N 分布 + 按天趋势）单元测试。

III-01 账号剔除根因可解释面板：验证 stats() 新增的 by_reason_top / trend
字段逻辑（Top N 排序、按天时间升序、向后兼容、边界钳制）。
使用 tmp 临时目录 + 预置 JSON 落盘，不写真实 data/。
"""

from __future__ import annotations

import json
from pathlib import Path

from services.trash_service import TrashService


def _entry(email: str, removed_at: str, reason: str, status: str = "异常") -> dict:
    return {
        "email": email,
        "access_token": f"tok-{email}",
        "status": status,
        "reason": reason,
        "source": "auto",
        "removed_at": removed_at,
        "detail": {},
    }


def _svc_with_entries(path: Path, entries: list[dict]) -> TrashService:
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return TrashService(path)


class TestTrashReasonStats:
    def test_by_reason_top_descending_and_limited(self, tmp_path):
        s = _svc_with_entries(
            tmp_path / "trash.json",
            [
                _entry("a@x.com", "2026-08-10T10:00:00+00:00", "account_deactivated"),
                _entry("b@x.com", "2026-08-10T11:00:00+00:00", "account_deactivated"),
                _entry("c@x.com", "2026-08-11T10:00:00+00:00", "token invalidated"),
                _entry("d@x.com", "2026-08-11T11:00:00+00:00", "quota exhausted"),
            ],
        )
        st = s.stats(top_reasons=2)
        assert st["by_reason_top"] == [
            {"reason": "account_deactivated", "count": 2},
            {"reason": "token invalidated", "count": 1},
        ]

    def test_by_reason_top_full_sorted(self, tmp_path):
        s = _svc_with_entries(
            tmp_path / "trash.json",
            [
                _entry("a@x.com", "2026-08-10T10:00:00+00:00", "r1"),
                _entry("b@x.com", "2026-08-10T11:00:00+00:00", "r2"),
                _entry("c@x.com", "2026-08-10T12:00:00+00:00", "r2"),
            ],
        )
        st = s.stats(top_reasons=10)
        assert [r["reason"] for r in st["by_reason_top"]] == ["r2", "r1"]

    def test_trend_ascending_by_day(self, tmp_path):
        s = _svc_with_entries(
            tmp_path / "trash.json",
            [
                _entry("a@x.com", "2026-08-10T10:00:00+00:00", "x"),
                _entry("b@x.com", "2026-08-08T10:00:00+00:00", "y"),
                _entry("c@x.com", "2026-08-10T12:00:00+00:00", "x"),
            ],
        )
        st = s.stats()
        assert st["trend"] == [
            {"day": "2026-08-08", "count": 1},
            {"day": "2026-08-10", "count": 2},
        ]

    def test_stats_backward_compatible(self, tmp_path):
        s = _svc_with_entries(
            tmp_path / "trash.json",
            [
                _entry("a@x.com", "2026-08-10T10:00:00+00:00", "x", status="异常"),
                _entry("b@x.com", "2026-08-10T11:00:00+00:00", "y", status="禁用"),
            ],
        )
        st = s.stats()
        # 原字段保留且完整
        assert st["total"] == 2
        assert st["by_status"]["异常"] == 1
        assert st["by_status"]["禁用"] == 1
        assert st["by_day"]["2026-08-10"] == 2
        assert st["by_reason"]["x"] == 1
        assert st["by_reason"]["y"] == 1
        # 新字段存在
        assert st["by_reason_top"]
        assert st["trend"]

    def test_top_reasons_clamped(self, tmp_path):
        s = _svc_with_entries(
            tmp_path / "trash.json",
            [
                _entry("a@x.com", "2026-08-10T10:00:00+00:00", "x"),
                _entry("b@x.com", "2026-08-10T11:00:00+00:00", "y"),
            ],
        )
        # 0 / 负数 → 至少 1 条
        assert len(s.stats(top_reasons=0)["by_reason_top"]) == 1
        assert len(s.stats(top_reasons=-5)["by_reason_top"]) == 1
        # 过大 → 不超过实际条数
        assert len(s.stats(top_reasons=999)["by_reason_top"]) == 2

    def test_empty_stats(self, tmp_path):
        s = TrashService(tmp_path / "trash.json")
        st = s.stats()
        assert st["total"] == 0
        assert st["by_reason_top"] == []
        assert st["trend"] == []
        assert st["by_status"] == {}
        assert st["by_day"] == {}
        assert st["by_reason"] == {}
