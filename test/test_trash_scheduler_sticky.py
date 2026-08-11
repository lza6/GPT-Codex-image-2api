"""回收站 + 雨露均沾调度 + 粘性 IP 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.account_service import AccountService
from services.config import config
from services.storage.json_storage import JSONStorageBackend
from services.trash_service import TrashService


# ====================================================================
# 回收站
# ====================================================================

class TestTrashService:
    def _svc(self, tmp_path: Path) -> TrashService:
        return TrashService(tmp_path / "trash.json")

    def test_add_and_list(self, tmp_path):
        s = self._svc(tmp_path)
        s.add(email="a@x.com", access_token="tok1", status="异常", reason="token invalidated", source="auto")
        s.add(email="b@x.com", access_token="tok2", status="禁用", reason="account_deactivated", source="relogin")
        items = s.list()
        assert len(items) == 2
        assert items[0]["email"] == "b@x.com"  # 新→旧

    def test_stats(self, tmp_path):
        s = self._svc(tmp_path)
        s.add(email="a@x.com", status="异常", reason="token invalidated", source="auto")
        s.add(email="b@x.com", status="禁用", reason="account_deactivated", source="relogin")
        s.add(email="c@x.com", status="禁用", reason="account_deactivated", source="relogin")
        st = s.stats()
        assert st["total"] == 3
        assert st["by_status"]["禁用"] == 2
        assert st["by_status"]["异常"] == 1
        assert st["by_reason"]["account_deactivated"] == 2

    def test_clear(self, tmp_path):
        s = self._svc(tmp_path)
        s.add(email="a@x.com", status="异常", source="auto")
        assert s.clear() == 1
        assert s.stats()["total"] == 0

    def test_restore(self, tmp_path):
        s = self._svc(tmp_path)
        s.add(email="a@x.com", status="禁用", source="auto")
        s.add(email="b@x.com", status="禁用", source="auto")
        r = s.restore(["a@x.com"])
        assert r["restored"] == 1
        remaining = s.list()
        assert len(remaining) == 1
        assert remaining[0]["email"] == "b@x.com"

    def test_add_from_account(self, tmp_path):
        s = self._svc(tmp_path)
        acct = {
            "email": "a@x.com",
            "access_token": "tok1",
            "status": "异常",
            "last_refresh_error": "token invalidated (/backend-api/me)",
            "invalid_count": 5,
        }
        s.add_from_account(acct, reason="token invalidated", source="auto")
        items = s.list()
        assert len(items) == 1
        assert items[0]["email"] == "a@x.com"
        assert items[0]["detail"]["invalid_count"] == 5

    def test_add_from_account_empty(self, tmp_path):
        s = self._svc(tmp_path)
        s.add_from_account(None, reason="x", source="y")
        assert s.stats()["total"] == 0

    def test_max_entries_capped(self, tmp_path):
        s = TrashService(tmp_path / "trash.json", max_entries=5)
        for i in range(10):
            s.add(email=f"{i}@x.com", status="异常", source="auto")
        assert s.stats()["total"] <= 5


# ====================================================================
# 雨露均沾调度（least_used）
# ====================================================================

class TestLeastUsedScheduler:
    def _svc(self, tmp_path):
        storage = JSONStorageBackend(tmp_path / "accounts.json")
        return AccountService(storage)

    def test_pick_least_used_picks_oldest_last_used(self, tmp_path):
        svc = self._svc(tmp_path)
        svc._accounts = {
            "t1": {"access_token": "t1", "last_used_at": "2026-08-01 00:00:00"},
            "t2": {"access_token": "t2", "last_used_at": "2026-08-10 00:00:00"},
            "t3": {"access_token": "t3", "last_used_at": "2026-08-05 00:00:00"},
        }
        picked = svc._pick_least_used(["t1", "t2", "t3"])
        assert picked == "t1"  # 最久未用（08-01）

    def test_pick_least_used_prefers_never_used(self, tmp_path):
        svc = self._svc(tmp_path)
        svc._accounts = {
            "t1": {"access_token": "t1", "last_used_at": "2026-08-10 00:00:00"},
            "t2": {"access_token": "t2"},  # 从未使用
        }
        picked = svc._pick_least_used(["t1", "t2"])
        assert picked == "t2"

    def test_pick_least_used_empty_raises(self, tmp_path):
        svc = self._svc(tmp_path)
        with pytest.raises(RuntimeError, match="no available tokens"):
            svc._pick_least_used([])


# ====================================================================
# 粘性 IP（kookeey 代理常规路径）
# ====================================================================

class TestStickyProxy:
    def test_sticky_proxy_uses_kookeey(self, monkeypatch, tmp_path):
        from services.proxy_service import ProxySettingsStore
        store = ProxySettingsStore()
        monkeypatch.setattr(
            "services.proxy_service.kookeey_proxy_for",
            lambda email: f"http://user:pass-US-{email[:4]}@gate:1000" if email else "",
        )
        p1 = store.get_profile(account={"email": "a@x.com", "access_token": "t1"})
        p2 = store.get_profile(account={"email": "b@x.com", "access_token": "t2"})
        assert p1.proxy_source == "kookeey_sticky"
        assert p1.proxy_url != p2.proxy_url  # 异号异 IP
        # 同号粘性
        p3 = store.get_profile(account={"email": "a@x.com", "access_token": "t1"})
        assert p1.proxy_url == p3.proxy_url
