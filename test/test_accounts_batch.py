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
