"""3.1.2：POST /api/accounts/batch 批量操作表驱动分发。

actions：evict_stale（按 ids 驱逐失效 token）/ label（批量打标签）/ export（批量导出）。
验收：各 action 分发正确、空 ids 拒绝、未知 action 拒绝、单点接口行为不变。
用 monkeypatch 替换 account_service 方法，不污染真实账号数据。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from services.account_service import account_service

_AUTH = {"Authorization": "Bearer chatgpt2api"}


def _client() -> TestClient:
    return TestClient(create_app())


class TestAccountsBatch:
    def test_evict_stale_dispatches_by_ids(self, monkeypatch) -> None:
        accounts = {
            "tok-1": {"access_token": "tok-1", "status": "异常"},
            "tok-2": {"access_token": "tok-2", "status": "正常"},
        }
        removed: list[str] = []
        monkeypatch.setattr(account_service, "get_account", lambda token: accounts.get(token))
        monkeypatch.setattr(
            account_service, "remove_invalid_token",
            lambda token, event, quiet=False: removed.append(token) or True,
        )
        client = _client()
        r = client.post(
            "/api/accounts/batch",
            json={"action": "evict_stale", "ids": ["tok-1", "tok-2"]},
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["action"] == "evict_stale"
        assert body["processed"] == 2
        assert body["evicted"] == 1  # 仅「异常」账号被驱逐
        assert removed == ["tok-1"]

    def test_label_dispatches(self, monkeypatch) -> None:
        updated: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            account_service, "update_account",
            lambda token, updates, quiet=False: updated.append((token, updates)) or {"access_token": token},
        )
        client = _client()
        r = client.post(
            "/api/accounts/batch",
            json={"action": "label", "ids": ["tok-1", "tok-2"], "label": "vip"},
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        assert r.json()["updated"] == 2
        assert updated == [("tok-1", {"label": "vip"}), ("tok-2", {"label": "vip"})]

    def test_label_rejects_empty_label(self) -> None:
        client = _client()
        r = client.post(
            "/api/accounts/batch",
            json={"action": "label", "ids": ["tok-1"], "label": "  "},
            headers=_AUTH,
        )
        assert r.status_code == 400

    def test_export_dispatches(self, monkeypatch) -> None:
        monkeypatch.setattr(
            account_service, "build_export_items",
            lambda ids: [{"access_token": token} for token in ids],
        )
        client = _client()
        r = client.post(
            "/api/accounts/batch",
            json={"action": "export", "ids": ["tok-1", "tok-2"]},
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["action"] == "export"
        assert body["count"] == 2
        assert len(body["items"]) == 2

    def test_empty_ids_rejected(self) -> None:
        client = _client()
        for action in ("evict_stale", "label", "export"):
            r = client.post(
                "/api/accounts/batch",
                json={"action": action, "ids": []},
                headers=_AUTH,
            )
            assert r.status_code == 400, f"{action} 空 ids 应拒绝"

    def test_unknown_action_rejected(self) -> None:
        client = _client()
        r = client.post(
            "/api/accounts/batch",
            json={"action": "reboot", "ids": ["tok-1"]},
            headers=_AUTH,
        )
        assert r.status_code == 400

    def test_requires_admin(self) -> None:
        client = _client()
        r = client.post("/api/accounts/batch", json={"action": "label", "ids": ["tok-1"], "label": "x"})
        assert r.status_code == 401

    def test_single_evict_stale_endpoint_unchanged(self, monkeypatch) -> None:
        """批量接口不改变单点 evict_stale 行为（全局驱逐）。"""
        calls = {"n": 0}

        def _fake_evict():
            calls["n"] += 1
            return {"stale": 0, "evicted": 0}

        monkeypatch.setattr("api.accounts._evict_stale_tokens", _fake_evict)
        client = _client()
        r = client.post("/api/accounts/evict_stale", headers=_AUTH)
        assert r.status_code == 200
        assert calls["n"] == 1

    def test_update_action_dispatches(self, monkeypatch) -> None:
        """批量更新 action 应正确分发。"""
        updated: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            account_service, "update_account",
            lambda token, updates, quiet=False: updated.append((token, updates)) or {"access_token": token},
        )
        client = _client()
        r = client.post(
            "/api/accounts/batch",
            json={"action": "update", "ids": ["tok-1", "tok-2"], "updates": {"proxy": "http://new-proxy:8080"}},
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["action"] == "update"
        assert body["updated"] == 2
        assert ("tok-1", {"proxy": "http://new-proxy:8080"}) in updated

    def test_update_action_empty_updates_rejected(self) -> None:
        """批量更新时 updates 为空应拒绝。"""
        client = _client()
        r = client.post(
            "/api/accounts/batch",
            json={"action": "update", "ids": ["tok-1"], "updates": {}},
            headers=_AUTH,
        )
        assert r.status_code == 400

    def test_update_action_partial_success(self, monkeypatch) -> None:
        """部分账号不存在时 errors 应包含失败信息。"""
        results: dict[str, dict | None] = {
            "tok-1": {"access_token": "tok-1"},
            "tok-2": None,  # 不存在
        }
        monkeypatch.setattr(
            account_service, "update_account",
            lambda token, updates, quiet=False: results.get(token),
        )
        client = _client()
        r = client.post(
            "/api/accounts/batch",
            json={"action": "update", "ids": ["tok-1", "tok-2"], "updates": {"priority": 5}},
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["action"] == "update"
        assert body["updated"] == 1
        assert len(body["errors"]) == 1
        assert "不存在" in body["errors"][0]["error"]

    def test_update_action_exception_handling(self, monkeypatch) -> None:
        """update_account 抛异常时 errors 应记录异常信息。"""
        def _raise_error(token, updates, quiet=False):
            raise ValueError("模拟数据库错误")
        monkeypatch.setattr(account_service, "update_account", _raise_error)
        client = _client()
        r = client.post(
            "/api/accounts/batch",
            json={"action": "update", "ids": ["tok-1"], "updates": {"proxy": "http://x"}},
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == 0
        assert len(body["errors"]) == 1
        assert "模拟数据库错误" in body["errors"][0]["error"]

    def test_update_action_multiple_fields(self, monkeypatch) -> None:
        """批量更新支持同时更新多个字段。"""
        updated: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            account_service, "update_account",
            lambda token, updates, quiet=False: updated.append((token, updates)) or {"access_token": token},
        )
        client = _client()
        r = client.post(
            "/api/accounts/batch",
            json={"action": "update", "ids": ["tok-1"], "updates": {"proxy": "http://p", "priority": 3, "tags": ["vip"]}},
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        assert r.json()["updated"] == 1
        assert len(updated) == 1
        _, updates = updated[0]
        assert updates["proxy"] == "http://p"
        assert updates["priority"] == 3
        assert updates["tags"] == ["vip"]

    def test_update_action_dedup_ids(self, monkeypatch) -> None:
        """重复的 ids 应被去重。"""
        updated: list[str] = []
        monkeypatch.setattr(
            account_service, "update_account",
            lambda token, updates, quiet=False: updated.append(token) or {"access_token": token},
        )
        client = _client()
        r = client.post(
            "/api/accounts/batch",
            json={"action": "update", "ids": ["tok-1", "tok-1", "tok-2"], "updates": {"label": "dup"}},
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        assert r.json()["updated"] == 2
        # tok-1 只应被处理一次
        assert updated.count("tok-1") == 1
        assert sorted(updated) == ["tok-1", "tok-2"]
