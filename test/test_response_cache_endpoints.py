"""V-02：只读高频端点响应缓存扩展测试。

新增缓存端点：/api/logs、/api/accounts/trash、/api/dashboard/usage、/api/dashboard/events。
覆盖：
- Cache-Control 响应头（命中与未命中均带）
- 命中缓存（不重复计算）+ 不同过滤条件互不串键
- ?refresh=1 强制刷新（绕过缓存重算）
- 写侧 invalidate：日志写入/回收站 add/clear/restore/事件持久化/用量 ingest →
  缓存立即失效（不读脏）
- TTL 注册与过期行为
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi.testclient import TestClient

import api.dashboard as dashboard_module
import api.response_cache as cache_module
import services.log_service as log_service_module
import services.trash_service as trash_module
import services.usage_agg as usage_agg_module
from api.app import _append_event_jsonl, create_app
from api.response_cache import response_cache
from services.event_bus import Event
from services.log_service import LogService
from services.trash_service import TrashService
from services.usage_agg import UsageAgg

_AUTH = {"Authorization": "Bearer chatgpt2api"}


def _client() -> TestClient:
    return TestClient(create_app())


def _log_entry(entry_id: str, summary: str) -> dict:
    return {
        "id": entry_id,
        "time": "2026-08-12 10:00:00",
        "type": "调用",
        "summary": summary,
        "detail": {"status": "success"},
    }


class TestNewPatternsRegistered:
    """新增模式已注册且 TTL 正确。"""

    def test_new_patterns_have_ttl(self) -> None:
        assert cache_module.response_cache.get_ttl("/api/logs") == 15
        assert cache_module.response_cache.get_ttl("/api/accounts/trash") == 15
        assert cache_module.response_cache.get_ttl("/api/dashboard/usage") == 15
        assert cache_module.response_cache.get_ttl("/api/dashboard/events") == 5


class TestLogsCache:
    def test_cache_control_header(self, monkeypatch) -> None:
        response_cache.invalidate()
        monkeypatch.setattr(log_service_module.log_service, "list", lambda **_k: [])
        resp = _client().get("/api/logs", headers=_AUTH)
        assert resp.status_code == 200
        assert resp.headers.get("Cache-Control") == "max-age=15"

    def test_hit_avoids_recompute(self, monkeypatch) -> None:
        response_cache.invalidate()
        calls = {"n": 0}

        def fake_list(**kwargs) -> list[dict]:
            calls["n"] += 1
            return [_log_entry("l1", "call-a")]

        monkeypatch.setattr(log_service_module.log_service, "list", fake_list)
        client = _client()
        r1 = client.get("/api/logs", headers=_AUTH)
        r2 = client.get("/api/logs", headers=_AUTH)
        assert r1.json() == r2.json()
        assert r1.headers.get("Cache-Control") == "max-age=15"  # 命中仍带头
        assert calls["n"] == 1, "第二次请求应命中缓存，不重复 list"

    def test_refresh_forces_recompute(self, monkeypatch) -> None:
        response_cache.invalidate()
        calls = {"n": 0}

        def fake_list(**kwargs) -> list[dict]:
            calls["n"] += 1
            return [_log_entry(f"l{calls['n']}", f"call-{calls['n']}")]

        monkeypatch.setattr(log_service_module.log_service, "list", fake_list)
        client = _client()
        client.get("/api/logs", headers=_AUTH)
        client.get("/api/logs?refresh=1", headers=_AUTH)
        assert calls["n"] == 2, "?refresh=1 应绕过缓存强制重算"

    def test_different_filters_distinct_keys(self, monkeypatch) -> None:
        response_cache.invalidate()
        calls = {"n": 0}

        def fake_list(**kwargs) -> list[dict]:
            calls["n"] += 1
            return [_log_entry(f"l{calls['n']}", str(kwargs.get("type") or ""))]

        monkeypatch.setattr(log_service_module.log_service, "list", fake_list)
        client = _client()
        client.get("/api/logs?type=%E8%B0%83%E7%94%A8", headers=_AUTH)
        client.get("/api/logs?type=account", headers=_AUTH)
        client.get("/api/logs?type=%E8%B0%83%E7%94%A8", headers=_AUTH)  # 同过滤 → 命中
        assert calls["n"] == 2, "不同过滤条件应各自缓存，同过滤二次命中"

    def test_delete_invalidates(self, monkeypatch) -> None:
        response_cache.invalidate()
        calls = {"n": 0}

        def fake_list(**kwargs) -> list[dict]:
            calls["n"] += 1
            return [_log_entry("l1", "call-a")]

        monkeypatch.setattr(log_service_module.log_service, "list", fake_list)
        monkeypatch.setattr(log_service_module.log_service, "delete", lambda ids: {"removed": 0})
        client = _client()
        client.get("/api/logs", headers=_AUTH)
        assert calls["n"] == 1
        client.post("/api/logs/delete", json={"ids": ["l1"]}, headers=_AUTH)
        client.get("/api/logs", headers=_AUTH)
        assert calls["n"] == 2, "删除后应失效缓存，下一次读取重新计算"

    def test_log_service_add_invalidates(self, tmp_path) -> None:
        """写侧失效：log_service.add 写入后 /api/logs 缓存被清空（不读脏）。"""
        response_cache.set("/api/logs", "stale")
        svc = LogService(tmp_path / "logs.jsonl")
        svc.add("调用", "new-call", {"status": "success"})
        assert response_cache.get("/api/logs") is None


class TestTrashCache:
    def test_cache_control_header(self, monkeypatch) -> None:
        response_cache.invalidate()
        monkeypatch.setattr(trash_module.trash_service, "list", lambda **k: [])
        monkeypatch.setattr(trash_module.trash_service, "stats", lambda **k: {"total": 0, "by_reason_top": [], "trend": []})
        resp = _client().get("/api/accounts/trash", headers=_AUTH)
        assert resp.status_code == 200
        assert resp.headers.get("Cache-Control") == "max-age=15"

    def test_hit_and_refresh(self, monkeypatch) -> None:
        response_cache.invalidate()
        calls = {"n": 0}

        def fake_stats(**kwargs) -> dict:
            calls["n"] += 1
            return {"total": calls["n"], "by_reason_top": [], "trend": []}

        monkeypatch.setattr(trash_module.trash_service, "list", lambda **k: [])
        monkeypatch.setattr(trash_module.trash_service, "stats", fake_stats)
        client = _client()
        r1 = client.get("/api/accounts/trash", headers=_AUTH)
        r2 = client.get("/api/accounts/trash", headers=_AUTH)
        assert r1.json() == r2.json()
        assert calls["n"] == 1
        client.get("/api/accounts/trash?refresh=1", headers=_AUTH)
        assert calls["n"] == 2, "?refresh=1 应绕过缓存"

    def test_different_params_distinct_keys(self, monkeypatch) -> None:
        response_cache.invalidate()
        calls = {"n": 0}

        def fake_stats(**kwargs) -> dict:
            calls["n"] += 1
            return {"total": calls["n"], "by_reason_top": [], "trend": []}

        monkeypatch.setattr(trash_module.trash_service, "list", lambda **k: [])
        monkeypatch.setattr(trash_module.trash_service, "stats", fake_stats)
        client = _client()
        client.get("/api/accounts/trash?limit=10&top_reasons=3", headers=_AUTH)
        client.get("/api/accounts/trash?limit=100&top_reasons=8", headers=_AUTH)
        client.get("/api/accounts/trash?limit=10&top_reasons=3", headers=_AUTH)
        assert calls["n"] == 2, "不同 limit/top_reasons 应各自缓存"

    def test_service_write_ops_invalidate(self, tmp_path) -> None:
        """写侧失效：add / clear / restore 后 /api/accounts/trash 缓存被清空。"""
        svc = TrashService(tmp_path / "trash.json")
        response_cache.set("/api/accounts/trash", "stale")
        svc.add(email="a@b.com", reason="invalid")
        assert response_cache.get("/api/accounts/trash") is None

        response_cache.set("/api/accounts/trash", "stale")
        svc.clear()
        assert response_cache.get("/api/accounts/trash") is None

        svc.add(email="c@d.com", reason="expired")
        response_cache.set("/api/accounts/trash", "stale")
        svc.restore(["c@d.com"])
        assert response_cache.get("/api/accounts/trash") is None

    def test_endpoint_no_stale_after_clear(self, monkeypatch) -> None:
        """不读脏：先命中缓存，clear 后再次读取得到空列表（非旧缓存）。"""
        response_cache.invalidate()
        state = {"items": [{"email": "a@b.com"}]}

        def fake_list(**kwargs):
            return list(state["items"])

        def fake_stats(**kwargs):
            return {"total": len(state["items"]), "by_reason_top": [], "trend": []}

        monkeypatch.setattr(trash_module.trash_service, "list", fake_list)
        monkeypatch.setattr(trash_module.trash_service, "stats", fake_stats)
        client = _client()
        r1 = client.get("/api/accounts/trash", headers=_AUTH)
        assert len(r1.json()["items"]) == 1
        state["items"] = []  # 模拟清空
        trash_module.trash_service.clear()  # 写操作 → invalidate
        r2 = client.get("/api/accounts/trash", headers=_AUTH)
        assert r2.json()["items"] == [], "clear 后不得读到旧缓存"


class TestUsageCache:
    def test_cache_control_header(self, monkeypatch) -> None:
        response_cache.invalidate()
        monkeypatch.setattr(usage_agg_module.usage_agg, "stats_for_window", lambda window: {"total_requests": 0, "by_summary": {}, "recent": []})
        resp = _client().get("/api/dashboard/usage", headers=_AUTH)
        assert resp.status_code == 200
        assert resp.headers.get("Cache-Control") == "max-age=15"

    def test_hit_and_refresh(self, monkeypatch) -> None:
        response_cache.invalidate()
        calls = {"n": 0}

        def fake_stats(window: int) -> dict:
            calls["n"] += 1
            return {"total_requests": calls["n"], "window": window}

        monkeypatch.setattr(usage_agg_module.usage_agg, "stats_for_window", fake_stats)
        client = _client()
        r1 = client.get("/api/dashboard/usage", headers=_AUTH)
        r2 = client.get("/api/dashboard/usage", headers=_AUTH)
        assert r1.json() == r2.json()
        assert calls["n"] == 1
        client.get("/api/dashboard/usage?refresh=1", headers=_AUTH)
        assert calls["n"] == 2

    def test_different_windows_distinct_keys(self, monkeypatch) -> None:
        response_cache.invalidate()
        calls = {"n": 0}

        def fake_stats(window: int) -> dict:
            calls["n"] += 1
            return {"total_requests": calls["n"], "window": window}

        monkeypatch.setattr(usage_agg_module.usage_agg, "stats_for_window", fake_stats)
        client = _client()
        client.get("/api/dashboard/usage?hours=24", headers=_AUTH)
        client.get("/api/dashboard/usage?hours=6", headers=_AUTH)
        client.get("/api/dashboard/usage?hours=24", headers=_AUTH)
        assert calls["n"] == 2, "不同窗口应各自缓存"

    def test_ingest_with_new_logs_invalidates(self, tmp_path) -> None:
        """写侧失效：usage_agg.ingest 摄入新日志后 /api/dashboard/usage 缓存被清空。"""
        logs = tmp_path / "logs.jsonl"
        logs.write_text(json.dumps({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": "调用",
            "summary": "gpt-4o",
            "detail": {"status": "success"},
        }) + "\n", encoding="utf-8")
        agg = UsageAgg(tmp_path / "usage_agg.json", logs)
        response_cache.set("/api/dashboard/usage", "stale")
        assert agg.ingest() == 1
        assert response_cache.get("/api/dashboard/usage") is None

    def test_ingest_without_new_logs_keeps_cache(self, tmp_path) -> None:
        """无新日志时 ingest 返回 0，不应打扰缓存。"""
        logs = tmp_path / "logs.jsonl"
        logs.write_text("", encoding="utf-8")
        agg = UsageAgg(tmp_path / "usage_agg.json", logs)
        response_cache.set("/api/dashboard/usage", "stale")
        assert agg.ingest() == 0
        assert response_cache.get("/api/dashboard/usage") == "stale"


class TestEventsCache:
    def test_cache_control_header(self, monkeypatch) -> None:
        response_cache.invalidate()
        monkeypatch.setattr(dashboard_module, "_fetch_recent_events", lambda limit=50: [])
        resp = _client().get("/api/dashboard/events", headers=_AUTH)
        assert resp.status_code == 200
        assert resp.headers.get("Cache-Control") == "max-age=5"

    def test_hit_and_refresh(self, monkeypatch) -> None:
        response_cache.invalidate()
        calls = {"n": 0}

        def fake_fetch(limit: int = 50) -> list[dict]:
            calls["n"] += 1
            return [{"id": f"e{calls['n']}", "type": "x", "data": {}, "timestamp": 1}]

        monkeypatch.setattr(dashboard_module, "_fetch_recent_events", fake_fetch)
        client = _client()
        r1 = client.get("/api/dashboard/events", headers=_AUTH)
        r2 = client.get("/api/dashboard/events", headers=_AUTH)
        assert r1.json() == r2.json()
        assert calls["n"] == 1
        client.get("/api/dashboard/events?refresh=1", headers=_AUTH)
        assert calls["n"] == 2

    def test_persist_event_invalidates(self, tmp_path) -> None:
        """写侧失效：事件持久化写入 events.jsonl 后 /api/dashboard/events 缓存被清空。"""
        events_path = tmp_path / "events.jsonl"
        response_cache.set("/api/dashboard/events", "stale")
        _append_event_jsonl(Event("account.invalid", {"token_suffix": "abcd1234"}), events_path)
        assert events_path.exists()
        assert response_cache.get("/api/dashboard/events") is None


class TestTtlExpiry:
    def test_ttl_expiry_invalidates_entry(self) -> None:
        """TTL 到期后条目自动过期（cachetools 语义）。"""
        c = cache_module.ResponseCache()
        c.register("/tmp-probe", ttl=1)
        c.set("/tmp-probe", "data")
        assert c.get("/tmp-probe") == "data"
        import time

        time.sleep(1.1)
        assert c.get("/tmp-probe") is None
